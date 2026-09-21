"""Source geometry pipeline for GloBI project ml testing."""

from pathlib import Path
from typing import cast

import boto3
import pandas as pd
import yaml
from epinterface.sbem.fields.spec import CategoricalFieldSpec, SemanticModelFields
from scythe.experiments import BaseExperiment
from scythe.scatter_gather import RecursionMap
from scythe.settings import ScytheStorageSettings

from globi.models.configs import (
    DeterministicGISPreprocessorConfig,
    FileConfig,
)
from globi.models.surrogate.backends.xgb import (
    XGBBackend,
    XGBModelConfig,
    XGBTrainerConfig,
)
from globi.models.surrogate.pipeline import (
    ConvergenceThresholds,
    ConvergenceThresholdsByTarget,
    CrossValidationSpec,
    FeatureConfigSpec,
    IterationSpec,
    ProgressiveTrainingSpec,
    RegressionIOConfigSpec,
    StratificationSpec,
    TargetsConfigGlobSpec,
)
from globi.models.surrogate.samplers import (
    CategoricalSampler,
    Priors,
    ProductValuesSampler,
    UnconditionalPrior,
    UniformSampler,
)
from globi.pipelines import iterative_training, simulate_globi_building
from globi.pipelines.gis import preprocess_gis_file


def geometry_extraction(
    config: DeterministicGISPreprocessorConfig,
    file_config: FileConfig,
):
    """Extract the geometry from the GIS file."""
    gdf, column_output_map = preprocess_gis_file(config, file_config)

    columns = {
        "building_id": column_output_map.Building_ID_col,
        "db_file": column_output_map.DB_File_col,
        "semantic_fields_file": column_output_map.Semantic_Fields_File_col,
        "component_map_file": column_output_map.Component_Map_File_col,
        "epwzip_file": column_output_map.EPWZip_File_col,
        "semantic_field_context": column_output_map.Semantic_Field_Context_col,
        "neighbor_polys": column_output_map.Neighbor_Polys_col,
        "neighbor_heights": column_output_map.Neighbor_Heights_col,
        "neighbor_floors": column_output_map.Neighbor_Floors_col,
        "rotated_rectangle": column_output_map.Rotated_Rectangle_col,
        "long_edge_angle": column_output_map.Long_Edge_Angle_col,
        "long_edge": column_output_map.Long_Edge_col,
        "short_edge": column_output_map.Short_Edge_col,
        "aspect_ratio": column_output_map.Aspect_Ratio_col,
        "rotated_rectangle_area_ratio": column_output_map.Rotated_Rectangle_Area_Ratio_col,
        "wwr": column_output_map.WWR_col,
        "height": column_output_map.Height_col,
        "num_floors": column_output_map.Num_Floors_col,
        "f2f_height": column_output_map.F2F_Height_col,
        "basement": column_output_map.Basement_col,
        "attic": column_output_map.Attic_col,
        "exposed_basement_frac": column_output_map.Exposed_Basement_Frac_col,
    }

    columns_to_pop = [
        "semantic_field_context",
        "f2f_height",
        "height",
        "basement",
        "attic",
        "exposed_basement_frac",
        "wwr",
    ]
    for column in columns_to_pop:
        columns.pop(column)
    gdf = cast(pd.DataFrame, gdf[list(columns.values())])
    gdf = gdf.rename(columns={v: k for k, v in columns.items()})
    return gdf


def main():
    """Main function."""
    config = DeterministicGISPreprocessorConfig(
        cart_crs="EPSG:3857",
        min_building_area=10.0,
        min_edge_length=3.0,
        max_edge_length=1000.0,
        neighbor_threshold=100.0,
        f2f_height=3.0,
        min_building_height=3.0,
        max_building_height=300.0,
        min_num_floors=1,
        max_num_floors=125,
        default_wwr=0.2,
        default_num_floors=2,
        default_basement="none",
        default_attic="none",
        default_exposed_basement_frac=0.25,
        epw_query="source in ['tmyx']",
    )

    file_config = FileConfig(
        gis_file=Path("tests/data/e2e/buildings.geojson"),
        semantic_fields_file=Path("tests/data/e2e/semantic-fields.yml"),
        component_map_file=Path("tests/data/e2e/component-map.yml"),
        db_file=Path("tests/data/e2e/components-lib.db"),
        epwzip_file=None,
    )

    df = geometry_extraction(config, file_config)
    # TODO: MAJOR REPLACEMENT REQUIRED FOR THIS
    settings = ScytheStorageSettings()
    semantic_field_key = (
        f"{settings.BUCKET_PREFIX}/test-experiment-artifacts/semantic-fields.yml"
    )
    component_map_key = (
        f"{settings.BUCKET_PREFIX}/test-experiment-artifacts/component-map.yml"
    )
    db_key = f"{settings.BUCKET_PREFIX}/test-experiment-artifacts/components-lib.db"
    semantic_fields_uri = f"s3://{settings.BUCKET}/{semantic_field_key}"
    component_map_uri = f"s3://{settings.BUCKET}/{component_map_key}"
    db_uri = f"s3://{settings.BUCKET}/{db_key}"
    df["semantic_fields_file"] = semantic_fields_uri
    df["component_map_file"] = component_map_uri
    df["db_file"] = db_uri
    df["rotated_rectangle"] = df["rotated_rectangle"].apply(lambda x: x.wkt)
    df["neighbor_polys"] = df["neighbor_polys"].apply(
        lambda x: [poly.wkt if poly is not None else None for poly in x]
    )

    s3 = boto3.client("s3")
    s3.upload_file(
        Filename=file_config.semantic_fields_file.as_posix(),
        Bucket=settings.BUCKET,
        Key=semantic_field_key,
    )
    s3.upload_file(
        Filename=file_config.component_map_file.as_posix(),
        Bucket=settings.BUCKET,
        Key=component_map_key,
    )
    s3.upload_file(
        Filename=file_config.db_file.as_posix(), Bucket=settings.BUCKET, Key=db_key
    )

    output_dir = Path("tests/data/training")
    output_dir.mkdir(parents=True, exist_ok=True)

    outpath = output_dir / "context.parquet"
    df.to_parquet(outpath)

    experiment_config = ProgressiveTrainingSpec(
        context=outpath,
        runnable=simulate_globi_building,
        base_run_name="test-simulations",
        convergence_criteria=ConvergenceThresholdsByTarget(
            thresholds={
                "EnergyAndPeakAnnual/Energy/Raw/**": ConvergenceThresholds(
                    mae=3,
                    rmse=5,
                    mape=0.05,
                    r2=0.975,
                    cvrmse=0.05,
                ),
                # "EnergyAndPeak/Energy/Raw/**": ConvergenceThresholds(
                #     r2=0.9,
                # ),
            }
        ),
        regression_io_config=RegressionIOConfigSpec(
            targets=TargetsConfigGlobSpec(
                globs=[
                    "EnergyAndPeakAnnual/*/Raw/**",
                ],
                normalization="min-max",
            ),
            features=FeatureConfigSpec(
                exclude_columns=frozenset(["building_id"]),
                cat_encoding="index",
            ),
        ),
        ml_backend=XGBBackend(
            hp=XGBModelConfig(
                max_depth=7,
                eta=0.1,
                min_child_weight=None,
                subsample=None,
                colsample_bytree=None,
                alpha=None,
                lam=None,
                gamma=None,
                seed=42,
            ),
            trainer=XGBTrainerConfig(
                num_boost_round=8000,
                early_stopping_rounds=10,
                verbose_eval=True,
            ),
        ),
        stratification=StratificationSpec(
            field="epwzip_file",
            sampling="equal",
        ),
        samplers=make_priors(file_config.semantic_fields_file),
        cross_val=CrossValidationSpec(
            n_folds=5,
        ),
        iteration=IterationSpec(
            n_per_iter=[500],
            min_per_stratum=25,
            max_iters=5,
            recursion=RecursionMap(
                factor=100,
                max_depth=1,
            ),
        ),
        storage_settings=settings,
        experiment_id="placeholder",
        sort_index=0,
    )

    exp = BaseExperiment(
        runnable=iterative_training,
        run_name=experiment_config.base_run_name,
        storage_settings=settings,
    )
    run, _ref = exp.allocate(
        experiment_config,
        version="bumpmajor",
    )
    print(yaml.dump(run.model_dump(mode="json"), indent=2, sort_keys=False))
    # sample_spec = SampleSpec(
    #     parent=experiment_config, priors=experiment_config.samplers
    # )
    # sample_df = sample_spec.populate_sample_df()


def make_priors(semantic_fields_file: Path):
    """Make priors for the uninitiated model."""
    with open(semantic_fields_file) as f:
        semantic_fields = SemanticModelFields.model_validate(yaml.safe_load(f))

    categorical_semantic_fields = [
        field
        for field in semantic_fields.Fields
        if isinstance(field, CategoricalFieldSpec)
    ]
    # numeric_semantic_field_names = [
    #     field for field in semantic_field_names if isinstance(field, NumericFieldSpec)
    # ]
    return Priors(
        sampled_features={
            "height": UnconditionalPrior(
                sampler=ProductValuesSampler(
                    features_to_multiply=["f2f_height", "num_floors"]
                )
            ),
            "f2f_height": UnconditionalPrior(
                sampler=UniformSampler(min=2.5, max=4, round=None)
            ),
            "wwr": UnconditionalPrior(
                sampler=UniformSampler(min=0.1, max=0.5, round=None)
            ),
            "basement": UnconditionalPrior(
                sampler=CategoricalSampler(
                    values=[
                        "none",
                        "unoccupied_unconditioned",
                        "unoccupied_conditioned",
                        "occupied_unconditioned",
                        "occupied_conditioned",
                    ],
                    weights=[0.5, 0.5 / 4, 0.5 / 4, 0.5 / 4, 0.5 / 4],
                )
            ),
            "attic": UnconditionalPrior(
                sampler=CategoricalSampler(
                    values=[
                        "none",
                        "unoccupied_unconditioned",
                        "unoccupied_conditioned",
                        "occupied_unconditioned",
                        "occupied_conditioned",
                    ],
                    weights=[0.5, 0.5 / 4, 0.5 / 4, 0.5 / 4, 0.5 / 4],
                )
            ),
            "exposed_basement_frac": UnconditionalPrior(
                sampler=UniformSampler(min=0.1, max=0.4, round=None)
            ),
            **{
                f"semantic_field_{field.Name}": UnconditionalPrior(
                    sampler=CategoricalSampler(
                        values=field.Options,
                        weights=[1 / len(field.Options) for _ in field.Options],
                    )
                )
                for field in categorical_semantic_fields
            },
            # TODO: add basement and attic priors
        }
    )


if __name__ == "__main__":
    main()
    # instance = GloBIBuildingSpec(
    #     building_id="test-building",
    #     experiment_id="test-experiment",
    #     sort_index=0,
    #     db_file="test-db.db",
    #     semantic_fields_file="test-semantic-fields.yml",
    #     component_map_file="test-component-map.yml",
    #     epwzip_file="test-epwzip.epw",
    #     semantic_field_context={},
    #     neighbor_polys=[],
    #     neighbor_heights=[],
    #     neighbor_floors=[],
    #     rotated_rectangle="test-rotated-rectangle.wkt",
    #     long_edge_angle=0,
    #     long_edge=10,
    #     short_edge=10,
    #     aspect_ratio=1,
    #     rotated_rectangle_area_ratio=100,
    #     wwr=0.2,
    #     height=10,
    #     num_floors=1,
    #     f2f_height=10,
    #     basement="none",
    #     attic="none",
    #     exposed_basement_frac=0.25,
    # )
    # instance.log = lambda msg: print(msg)
