"""GIS-based geometry selection + priors-based parameter sampling.

Merges building geometry from a preprocessed GIS file with
FlatModel parameters sampled from a Priors dependency graph.
"""

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from scythe.utils.filesys import FileReference

from globi.models.configs import GISPreprocessorColumnMap
from globi.models.sampling import Priors
from globi.models.surrogate import TrainingSimInputSpec

logger = logging.getLogger(__name__)


def stratified_sample_buildings(
    gis_gdf: gpd.GeoDataFrame,
    colmap: GISPreprocessorColumnMap,
    n: int,
    generator: np.random.Generator,
) -> gpd.GeoDataFrame:
    """Sample buildings from GIS, stratified by weather file (equal per stratum).

    Args:
        gis_gdf: Preprocessed GIS GeoDataFrame.
        colmap: Column name mapping from GIS preprocessing.
        n: Total number of buildings to sample.
        generator: Random generator for reproducibility.

    Returns:
        Sampled GeoDataFrame subset (with replacement).
    """
    epw_col = colmap.EPWZip_File_col
    strata = gis_gdf[epw_col].unique()
    n_strata = len(strata)
    n_per_stratum = n // n_strata
    remainder = n % n_strata

    sampled_dfs: list[gpd.GeoDataFrame] = []
    for i, stratum in enumerate(strata):
        stratum_gdf = gis_gdf[gis_gdf[epw_col] == stratum]
        n_this = n_per_stratum + (1 if i < remainder else 0)
        indices = generator.choice(len(stratum_gdf), size=n_this, replace=True)
        sampled_dfs.append(stratum_gdf.iloc[indices])

    result = gpd.GeoDataFrame(pd.concat(sampled_dfs, ignore_index=True))
    return result


def sample_training_specs(
    gis_gdf: gpd.GeoDataFrame,
    colmap: GISPreprocessorColumnMap,
    priors: Priors,
    n: int,
    generator: np.random.Generator,
) -> list[TrainingSimInputSpec]:
    """Sample training specs by selecting buildings from GIS and sampling FlatModel parameters from priors.

    Flow:
    1. Stratify GIS buildings by weather file, sample n buildings
    2. Extract geometry from each selected building
    3. Build context DataFrame with GIS-derived columns
    4. Sample all prior-governed FlatModel parameters
    5. Construct TrainingSimInputSpec per row

    Args:
        gis_gdf: Preprocessed GIS GeoDataFrame with rotated rectangles and neighbors.
        colmap: Column name mapping from GIS preprocessing.
        priors: Sampling graph whose terminal nodes map to FlatModel field names.
        n: Number of training specs to generate.
        generator: Random generator for reproducibility.

    Returns:
        List of TrainingSimInputSpec instances ready for Scythe allocation.
    """
    sampled = stratified_sample_buildings(gis_gdf, colmap, n, generator)

    context = pd.DataFrame(index=range(len(sampled)))
    context["Width"] = sampled[colmap.Long_Edge_col].values
    context["Depth"] = sampled[colmap.Short_Edge_col].values
    context["NFloors"] = sampled[colmap.Num_Floors_col].values.astype(int)
    context["Rotation"] = np.degrees(
        sampled[colmap.Long_Edge_Angle_col].values.astype(float)
    )

    context = priors.sample(context, len(context), generator)

    specs: list[TrainingSimInputSpec] = []
    for i in range(len(sampled)):
        row = sampled.iloc[i]
        context_row = context.iloc[i]

        flat_model_params: dict = {}
        for col in context.columns:
            val = context_row[col]
            if isinstance(val, np.integer):
                val = int(val)
            elif isinstance(val, np.floating):
                val = float(val)
            flat_model_params[col] = val

        epw_uri: FileReference = row[colmap.EPWZip_File_col]

        flat_model_params["EPWURI"] = str(epw_uri)

        neighbor_polys = row.get(colmap.Neighbor_Polys_col, []) or []
        neighbor_heights = row.get(colmap.Neighbor_Heights_col, []) or []
        neighbor_floors = row.get(colmap.Neighbor_Floors_col, []) or []

        if not isinstance(neighbor_polys, list):
            neighbor_polys = []
        if not isinstance(neighbor_heights, list):
            neighbor_heights = []
        if not isinstance(neighbor_floors, list):
            neighbor_floors = []

        spec = TrainingSimInputSpec(
            experiment_id=f"training_sim_{i:06d}",
            sort_index=i,
            flat_model_params=flat_model_params,
            epw_uri=epw_uri,
            width=float(row[colmap.Long_Edge_col]),
            depth=float(row[colmap.Short_Edge_col]),
            num_floors=int(row[colmap.Num_Floors_col]),
            rotation=float(np.degrees(row[colmap.Long_Edge_Angle_col])),
            rotated_rectangle=str(row[colmap.Rotated_Rectangle_col]),
            long_edge_angle=float(row[colmap.Long_Edge_Angle_col]),
            neighbor_polys=neighbor_polys,
            neighbor_heights=neighbor_heights,
            neighbor_floors=neighbor_floors,
            weather_file_id=str(epw_uri).split("/")[-1].replace(".zip", "")
            if isinstance(epw_uri, str)
            else "",
        )
        specs.append(spec)

    logger.info(f"Sampled {len(specs)} training specs from GIS.")
    return specs
