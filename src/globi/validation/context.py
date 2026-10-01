"""Build the GIS context, priors and training spec for a local surrogate run.

The training *context* is the deterministic geometry of a building stock (footprints,
neighbours, floors, weather file) with the prior-sampled attributes removed.  The
sampler (`globi.models.surrogate.samplers.Priors`) then fills in semantic fields,
window-to-wall ratio, floor-to-floor height, etc. for each training sample.
"""

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import cast

import geopandas as gpd
import pandas as pd
import yaml
from epinterface.sbem.fields.spec import (
    CategoricalFieldSpec,
    NumericFieldSpec,
    SemanticModelFields,
)
from scythe.scatter_gather import RecursionMap
from scythe.settings import ScytheStorageSettings
from scythe.utils.filesys import S3Url

from globi.models.configs import (
    DeterministicGISPreprocessorConfig,
    FileConfig,
    GISPreprocessorColumnMap,
    GloBIExperimentSpec,
)
from globi.models.surrogate.backends import MLBackend, XGBBackend
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
from globi.pipelines.gis import preprocess_gis_file

logger = logging.getLogger(__name__)

# Columns of the preprocessed GIS frame that become GloBIBuildingSpec fields, keyed by
# the spec field name.  Values are attribute names on GISPreprocessorColumnMap.
_CONTEXT_COLUMNS: dict[str, str] = {
    "building_id": "Building_ID_col",
    "db_file": "DB_File_col",
    "semantic_fields_file": "Semantic_Fields_File_col",
    "component_map_file": "Component_Map_File_col",
    "epwzip_file": "EPWZip_File_col",
    "neighbor_polys": "Neighbor_Polys_col",
    "neighbor_heights": "Neighbor_Heights_col",
    "neighbor_floors": "Neighbor_Floors_col",
    "rotated_rectangle": "Rotated_Rectangle_col",
    "long_edge_angle": "Long_Edge_Angle_col",
    "long_edge": "Long_Edge_col",
    "short_edge": "Short_Edge_col",
    "aspect_ratio": "Aspect_Ratio_col",
    "rotated_rectangle_area_ratio": "Rotated_Rectangle_Area_Ratio_col",
    "num_floors": "Num_Floors_col",
}

FILE_COLUMNS = ("db_file", "semantic_fields_file", "component_map_file")

#: Index columns that must never become surrogate features: unique per building
#: (`building_id`, `rotated_rectangle`) or unused by the simulator (`height`, which the
#: model derives from `f2f_height * num_floors`).
DEFAULT_EXCLUDED_FEATURE_COLUMNS = frozenset({
    "building_id",
    "rotated_rectangle",
    "height",
})

DEFAULT_TARGET_GLOBS = ("EnergyAndPeakAnnual/Energy/Raw/*",)

BASEMENT_ATTIC_OPTIONS = [
    "none",
    "unoccupied_unconditioned",
    "unoccupied_conditioned",
    "occupied_unconditioned",
    "occupied_conditioned",
]


def build_training_context(
    config: DeterministicGISPreprocessorConfig,
    file_config: FileConfig,
    *,
    scenario: str | None = None,
    exclude_building_ids: Iterable[str] | None = None,
    file_refs: dict[str, str] | None = None,
    preprocessed: tuple[gpd.GeoDataFrame, GISPreprocessorColumnMap] | None = None,
) -> pd.DataFrame:
    """Preprocess a GIS file into a parquet-serializable training context.

    Args:
        config: GIS preprocessor config.
        file_config: File config (GIS, db, semantic fields, component map, epw).
        scenario: Optional scenario override passed to the preprocessor.
        exclude_building_ids: Buildings to hold out (e.g. the validation set).
        file_refs: Optional overrides for the `db_file` / `semantic_fields_file` /
            `component_map_file` columns (e.g. s3 uris for a remote run).
        preprocessed: An already preprocessed `(gdf, colmap)` pair to use instead of
            running `preprocess_gis_file` again.

    Returns:
        A frame with one row per building whose columns are `GloBIBuildingSpec` field
        names.  Prior-sampled fields (semantic fields, wwr, f2f_height, basement, attic,
        exposed_basement_frac, height) are intentionally absent.
    """
    gdf, colmap = preprocessed or preprocess_gis_file(
        config, file_config, scenario=scenario
    )
    columns = {field: getattr(colmap, attr) for field, attr in _CONTEXT_COLUMNS.items()}
    df = cast(pd.DataFrame, pd.DataFrame(gdf[list(columns.values())]))
    df = df.rename(columns={v: k for k, v in columns.items()})

    if exclude_building_ids is not None:
        excluded = set(exclude_building_ids)
        before = len(df)
        df = cast(pd.DataFrame, df[~df["building_id"].isin(list(excluded))])
        logger.info("Held out %d buildings from training context.", before - len(df))

    # geometries and file references must be plain strings to round-trip via parquet
    df["rotated_rectangle"] = df["rotated_rectangle"].apply(lambda g: g.wkt)
    df["neighbor_polys"] = df["neighbor_polys"].apply(
        lambda polys: [poly.wkt if poly is not None else None for poly in polys]
    )
    for col in (*FILE_COLUMNS, "epwzip_file"):
        df[col] = df[col].astype(str)
    for col, ref in (file_refs or {}).items():
        df[col] = ref

    return df.reset_index(drop=True)


def default_priors_from_semantic_fields(
    semantic_fields_file: Path,
    *,
    fixed_basement_attic: bool = True,
    f2f_height: tuple[float, float] = (2.5, 4.0),
    wwr: tuple[float, float] = (0.1, 0.5),
    exposed_basement_frac: tuple[float, float] = (0.1, 0.4),
) -> Priors:
    """Uniform priors over every semantic field plus basic geometry knobs.

    Categorical fields are sampled uniformly over their options; numeric fields
    uniformly over their `[Min, Max]` range.

    Args:
        semantic_fields_file: The semantic fields yaml.
        fixed_basement_attic: Pin basement/attic to "none" (keeps the spec validators
            deterministic and shrinks the prior space for small samples).
        f2f_height: Uniform range for floor-to-floor height [m].
        wwr: Uniform range for window-to-wall ratio.
        exposed_basement_frac: Uniform range for the exposed basement fraction.
    """
    with open(semantic_fields_file) as f:
        semantic_fields = SemanticModelFields.model_validate(yaml.safe_load(f))
    semantic_priors: dict[str, UnconditionalPrior] = {}
    for field in semantic_fields.Fields:
        if isinstance(field, CategoricalFieldSpec):
            sampler = CategoricalSampler(
                values=list(field.Options),
                weights=[1 / len(field.Options)] * len(field.Options),
            )
        elif isinstance(field, NumericFieldSpec):
            sampler = UniformSampler(min=field.Min, max=field.Max)
        else:
            msg = f"No default prior for semantic field {field.Name!r} of type {type(field).__name__}."
            raise NotImplementedError(msg)
        semantic_priors[f"semantic_field_{field.Name}"] = UnconditionalPrior(
            sampler=sampler
        )

    if fixed_basement_attic:
        basement_attic_sampler = CategoricalSampler(values=["none"], weights=[1.0])
    else:
        n_other = len(BASEMENT_ATTIC_OPTIONS) - 1
        basement_attic_sampler = CategoricalSampler(
            values=BASEMENT_ATTIC_OPTIONS,
            weights=[0.5, *[0.5 / n_other] * n_other],
        )

    return Priors(
        sampled_features={
            "f2f_height": UnconditionalPrior(
                sampler=UniformSampler(min=f2f_height[0], max=f2f_height[1])
            ),
            "height": UnconditionalPrior(
                sampler=ProductValuesSampler(
                    features_to_multiply=["f2f_height", "num_floors"]
                )
            ),
            "wwr": UnconditionalPrior(sampler=UniformSampler(min=wwr[0], max=wwr[1])),
            "basement": UnconditionalPrior(sampler=basement_attic_sampler),
            "attic": UnconditionalPrior(sampler=basement_attic_sampler),
            "exposed_basement_frac": UnconditionalPrior(
                sampler=UniformSampler(
                    min=exposed_basement_frac[0], max=exposed_basement_frac[1]
                )
            ),
            **semantic_priors,
        }
    )


def build_training_spec(
    manifest: GloBIExperimentSpec,
    *,
    context_path: Path | S3Url,
    ml_backend: MLBackend | None = None,
    priors: Priors | None = None,
    n_per_iter: int | list[int] = 32,
    min_per_stratum: int = 8,
    max_iters: int = 1,
    n_folds: int = 4,
    targets_globs: Iterable[str] = DEFAULT_TARGET_GLOBS,
    exclude_columns: Iterable[str] = DEFAULT_EXCLUDED_FEATURE_COLUMNS,
    thresholds: dict[str, ConvergenceThresholds] | None = None,
    base_run_name: str = "local-surrogate",
    storage_settings: ScytheStorageSettings | None = None,
) -> ProgressiveTrainingSpec:
    """Assemble a `ProgressiveTrainingSpec` that simulates real GloBI buildings.

    The spec is runnable in-process via `globi.validation.local_runner` when
    `storage_settings` is None, or submitted to hatchet via `globi submit surrogate`
    when the context and file references live on s3.
    """
    # imported lazily: registers the runnable and needs the hatchet env
    from globi.pipelines.simulations import simulate_globi_building

    return ProgressiveTrainingSpec(
        experiment_id="placeholder",
        sort_index=0,
        storage_settings=storage_settings,
        runnable=simulate_globi_building,
        base_run_name=base_run_name,
        context=context_path,
        convergence_criteria=ConvergenceThresholdsByTarget(
            thresholds=thresholds or {"*": ConvergenceThresholds(r2=0.95)}
        ),
        regression_io_config=RegressionIOConfigSpec(
            targets=TargetsConfigGlobSpec(
                globs=list(targets_globs), normalization="min-max"
            ),
            features=FeatureConfigSpec(
                exclude_columns=frozenset(exclude_columns),
                cat_encoding="index",
            ),
        ),
        ml_backend=ml_backend or XGBBackend(),
        stratification=StratificationSpec(field="epwzip_file", sampling="equal"),
        samplers=priors
        or default_priors_from_semantic_fields(
            manifest.file_config.semantic_fields_file
        ),
        cross_val=CrossValidationSpec(n_folds=n_folds),
        iteration=IterationSpec(
            n_per_iter=n_per_iter,
            min_per_stratum=min_per_stratum,
            max_iters=max_iters,
            recursion=RecursionMap(factor=100, max_depth=1),
        ),
    )


def upload_context_artifacts(
    context: pd.DataFrame,
    file_config: FileConfig,
    storage_settings: ScytheStorageSettings,
    *,
    key_prefix: str = "local-surrogate-artifacts",
    context_path: Path,
) -> tuple[pd.DataFrame, S3Url]:
    """Upload the db / semantic fields / component map and context parquet to s3.

    Used to hand a locally-built context to the hatchet workflow (e.g. the docker +
    hatchet-lite + localstack stack).  Returns the context with s3 file references
    substituted in, and the s3 uri of the uploaded context parquet.
    """
    import boto3

    s3 = boto3.client("s3")
    prefix = f"{storage_settings.BUCKET_PREFIX}/{key_prefix}"
    local_files = {
        "db_file": file_config.db_file,
        "semantic_fields_file": file_config.semantic_fields_file,
        "component_map_file": file_config.component_map_file,
    }
    context = context.copy()
    for col, local_path in local_files.items():
        key = f"{prefix}/{Path(local_path).name}"
        s3.upload_file(
            Filename=Path(local_path).as_posix(),
            Bucket=storage_settings.BUCKET,
            Key=key,
        )
        context[col] = f"s3://{storage_settings.BUCKET}/{key}"

    context_path.parent.mkdir(parents=True, exist_ok=True)
    context.to_parquet(context_path)
    context_key = f"{prefix}/{context_path.name}"
    s3.upload_file(
        Filename=context_path.as_posix(),
        Bucket=storage_settings.BUCKET,
        Key=context_key,
    )
    return context, S3Url(f"s3://{storage_settings.BUCKET}/{context_key}")
