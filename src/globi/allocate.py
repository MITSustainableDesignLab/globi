"""Allocate a GloBI experiment with Scythe."""

import logging
from pathlib import Path

import boto3
import geopandas as gpd
import yaml
from epinterface.sbem.fields.spec import SemanticModelFields
from epinterface.sbem.utils import check_model_existence
from scythe.base import ExperimentInputSpec, ExperimentOutputSpec
from scythe.experiments import BaseExperiment
from scythe.scatter_gather import RecursionMap
from shapely import to_wkt
from tqdm import tqdm

from globi.branching import calculate_branching_factor
from globi.models.configs import GloBIExperimentSpec
from globi.models.tasks import GloBIBuildingSpec
from globi.pipelines import preprocess_gis_file, simulate_globi_building

s3_client = boto3.client("s3")

logger = logging.getLogger(__name__)

# TODO: replace prints with logs


def allocate_globi_experiment(
    config: GloBIExperimentSpec,
    check_model_constructability: bool = True,
    max_sims: int | None = None,
):
    """Deploy an experiment from a config."""
    print("Deploying experiment from config:")
    print(yaml.dump(config.model_dump(mode="json"), indent=2, sort_keys=False))
    name = f"{config.name}/{config.scenario}"

    if check_model_constructability:
        check_model_existence(
            component_map_path=config.file_config.component_map_file,
            semantic_fields_path=config.file_config.semantic_fields_file,
            db_path=config.file_config.db_file,
            raise_on_error=True,
        )

    # if config.gis_preprocessor_config:
    buildings_gdf, colmap = preprocess_gis_file(
        # TODO: make this required on the original model
        config=config.gis_preprocessor_config,
        file_config=config.file_config,
        scenario=config.scenario,
    )

    specs: list[GloBIBuildingSpec] = []

    if max_sims:
        buildings_gdf = buildings_gdf.sample(min(max_sims, len(buildings_gdf)))

    for sort_index, (_, row) in tqdm(
        enumerate(buildings_gdf.iterrows()),
        total=len(buildings_gdf),
        desc="Generating building specs from GIS:",
    ):
        row = row.to_dict()
        globi_spec = GloBIBuildingSpec(
            building_id=row[colmap.Building_ID_col],
            experiment_id="placeholder",
            sort_index=sort_index,
            db_file=row[colmap.DB_File_col],
            semantic_fields_file=config.file_config.semantic_fields_file,
            component_map_file=config.file_config.component_map_file,
            epwzip_file=row[colmap.EPWZip_File_col],
            semantic_field_context=row[colmap.Semantic_Field_Context_col],
            neighbor_polys=[to_wkt(poly) for poly in row[colmap.Neighbor_Polys_col]],
            neighbor_heights=row[colmap.Neighbor_Heights_col],
            neighbor_floors=row[colmap.Neighbor_Floors_col],
            rotated_rectangle=to_wkt(row[colmap.Rotated_Rectangle_col]),
            long_edge_angle=row[colmap.Long_Edge_Angle_col],
            long_edge=row[colmap.Long_Edge_col],
            short_edge=row[colmap.Short_Edge_col],
            aspect_ratio=row[colmap.Aspect_Ratio_col],
            rotated_rectangle_area_ratio=row[colmap.Rotated_Rectangle_Area_Ratio_col],
            wwr=row[colmap.WWR_col],
            height=row[colmap.Height_col],
            num_floors=row[colmap.Num_Floors_col],
            f2f_height=row[colmap.F2F_Height_col],
            basement=row[colmap.Basement_col],
            attic=row[colmap.Attic_col],
            exposed_basement_frac=row[colmap.Exposed_Basement_Frac_col],
            parent_experiment_spec=config,
        )
        specs.append(globi_spec)

    if not specs:
        msg = "No specs provided"
        raise ValueError(msg)

    experiment = BaseExperiment[ExperimentInputSpec, ExperimentOutputSpec](
        runnable=simulate_globi_building, run_name=name
    )
    print(f"Submitting {len(buildings_gdf)} buildings for experiment {name}")
    min_branches_required, _, _ = calculate_branching_factor(specs)

    run, ref = experiment.allocate(
        specs,
        version="bumpminor",
        recursion_map=RecursionMap(factor=min_branches_required, max_depth=1),
        s3_client=s3_client,
    )

    print(yaml.dump(run.model_dump(mode="json"), indent=2, sort_keys=False))
    return run, ref


def allocate_globi_dryrun(
    config: GloBIExperimentSpec,
    epwzip_file: Path | str | None = None,
    max_tests: int | None = None,
):
    """Dry run the allocation of an experiment to estimate the cost."""
    from shapely import Polygon, to_wkt

    epwzip_file = epwzip_file or config.file_config.epwzip_file
    if epwzip_file is None:
        msg = "EPWZip file is required for dry run"
        raise ValueError(msg)

    with open(config.file_config.semantic_fields_file) as f:
        model = SemanticModelFields.model_validate(yaml.safe_load(f))

    grid, field_vals = model.make_grid(numerical_discretization=10)
    grid = grid.sample(min(max_tests or len(grid), len(grid)))

    width = 12  # meters
    basic_rectangle = Polygon([(0, 0), (width, 0), (width, width), (0, width), (0, 0)])

    specs: list[GloBIBuildingSpec] = []
    for i, (_, row) in enumerate(grid.iterrows()):
        context = row.to_dict()
        # first we need to update the context with the field values
        for field_name, field_val in field_vals.items():
            context[field_name] = field_val[context[field_name]]
        spec = GloBIBuildingSpec(
            experiment_id="placeholder",
            sort_index=0,
            db_file=config.file_config.db_file,
            semantic_fields_file=config.file_config.semantic_fields_file,
            component_map_file=config.file_config.component_map_file,
            epwzip_file=epwzip_file,  # pyright: ignore [reportArgumentType]
            semantic_field_context=context,
            neighbor_polys=[],
            neighbor_heights=[],
            neighbor_floors=[],
            rotated_rectangle=to_wkt(basic_rectangle),
            long_edge_angle=0,
            long_edge=width,
            short_edge=width,
            aspect_ratio=1,
            rotated_rectangle_area_ratio=width * width,
            wwr=config.gis_preprocessor_config.default_wwr,
            height=config.gis_preprocessor_config.default_num_floors
            * config.gis_preprocessor_config.f2f_height,
            num_floors=config.gis_preprocessor_config.default_num_floors,
            f2f_height=config.gis_preprocessor_config.f2f_height,
            basement=config.gis_preprocessor_config.default_basement,
            attic=config.gis_preprocessor_config.default_attic,
            exposed_basement_frac=config.gis_preprocessor_config.default_exposed_basement_frac,
            building_id=f"dryrun_{i:05d}",
        )
        specs.append(spec)

    min_branches_required, _, _ = calculate_branching_factor(specs)

    if not specs:
        msg = "No specs provided"
        raise ValueError(msg)

    experiment = BaseExperiment[ExperimentInputSpec, ExperimentOutputSpec](
        runnable=simulate_globi_building,
        run_name=f"{config.name}/dryrun/{config.scenario}",
    )

    run, ref = experiment.allocate(
        specs,
        version="bumpminor",
        recursion_map=RecursionMap(factor=min_branches_required, max_depth=1),
        s3_client=s3_client,
    )

    print(yaml.dump(run.model_dump(mode="json"), indent=2, sort_keys=False))
    return run, ref


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    spec = GloBIExperimentSpec.from_(Path("data/partners/Cambridge_UK/manifest.yml"))
    print(yaml.dump(spec.model_dump(mode="json"), indent=2, sort_keys=False))
    # gdf = gpd.read_file(spec.file_config.gis_file)
    logging.basicConfig(level=logging.DEBUG)
    if spec.gis_preprocessor_config is not None:
        new_gdf_path = spec.file_config.gis_file.parent / "buildings-updated.geojson"
        old_gdf: gpd.GeoDataFrame = gpd.read_file(spec.file_config.gis_file)
        old_gdf["Region"] = "CB"
        old_gdf["Age_bracket"] = (
            old_gdf["Age_bracket"].str.replace(" ", "_").str.replace("1999", "1960")
        )
        old_gdf["OCCUPANCY_DENSITY"] = old_gdf["OCCUPANCY_DENSITY"].str.replace(
            "MediumDensity", "MedDensity"
        )
        old_gdf.to_file(new_gdf_path, driver="GeoJSON")
        spec.file_config.gis_file = new_gdf_path
        allocate_globi_experiment(spec)
