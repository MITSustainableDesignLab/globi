"""Data source abstraction for local and S3 data loading."""

from __future__ import annotations

import functools
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from scythe.settings import ScytheStorageSettings

from globi.tools.visualization.models import (
    DataSourceConfig,
    LocalDataSourceConfig,
    S3DataSourceConfig,
)
from globi.tools.visualization.utils import (
    build_overheating_map_df,
    build_overheating_summary_df,
    build_overheating_threshold_curves_df,
    find_output_run_dirs,
    get_overheating_thresholds,
    get_pq_file_for_run,
    list_overheating_files_for_run,
    load_heat_index_summary_for_chart,
    load_output_table,
    read_geo_file,
    run_has_overheating,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


_VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
# final result files fetched for a run; the first one present is the run's main table
_S3_RESULT_STEMS = ("EnergyAndPeak", "Results")
_S3_OVERHEATING_STEMS = (
    "BasicOverheating",
    "ExceedanceDegreeHours",
    "HeatIndexCategories",
    "ConsecutiveExceedances",
)


def _get_s3_prefixes(
    s3_client: S3Client,
    bucket: str,
    prefix: str,
) -> list[str]:
    """List all common prefixes under a given S3 prefix."""
    paginator = s3_client.get_paginator("list_objects_v2")
    prefixes: list[str] = []
    for page in paginator.paginate(
        Bucket=bucket,
        Prefix=prefix,
        Delimiter="/",
        PaginationConfig={"PageSize": 1000},
    ):
        for common_prefix in page.get("CommonPrefixes", []):
            p = common_prefix.get("Prefix", "")
            if p:
                prefixes.append(p)
    return prefixes


def _run_sort_key(run_id: str) -> tuple:
    """Sort by experiment path, then numerically by version."""
    path, _, version = run_id.rpartition("/")
    m = _VERSION_RE.match(version)
    return (path, tuple(int(x) for x in m.groups()) if m else (0, 0, 0))


def list_s3_runs(
    s3_client: S3Client,
    bucket: str,
    prefix: str,
    max_depth: int = 4,
) -> list[str]:
    """Run ids under prefix, e.g. "MA_Commercial/ASHPOnly/v1.0.0".

    Walks folders until it reaches version folders (vX.Y.Z), so experiment
    names may be nested (scythe run names can contain "/").
    """
    runs: list[str] = []

    def walk(p: str, depth: int) -> None:
        for child in _get_s3_prefixes(s3_client, bucket, p):
            if _VERSION_RE.match(child[len(p) :].rstrip("/")):
                runs.append(child[len(prefix) :].rstrip("/"))
            elif depth < max_depth:
                walk(child, depth + 1)

    walk(prefix, 0)
    return sorted(runs, key=_run_sort_key)


class DataSource(ABC):
    """Abstract base class for data sources."""

    @abstractmethod
    def list_available_runs(self) -> list[str]:
        """List available run identifiers."""
        ...

    @abstractmethod
    def load_run_data(self, run_id: str) -> pd.DataFrame:
        """Load data for a specific run."""
        ...

    @abstractmethod
    def load_building_locations(self) -> pd.DataFrame | None:
        """Load building attributes from inputs (or equivalent) when run-local parquet is absent."""
        ...

    def list_runs_with_overheating(self) -> list[str]:
        """List run ids that have overheating outputs. Override for support."""
        return []

    def list_overheating_files(self, run_id: str) -> list[str]:
        """List available overheating df keys for a run. Override for support."""
        return []

    def load_overheating_map_data(
        self,
        run_id: str,
        cart_crs: str = "EPSG:3857",
        heat_threshold_c: float = 26.0,
        aggregation: str = "Zone Weighted",
        data_source_type: str = "BasicOverheating",
        heat_index_metric: str = "danger_hours",
    ) -> pd.DataFrame | None:
        """Load map-ready overheating data for a run. Override for support."""
        return None

    def load_overheating_heat_index_summary(
        self,
        run_id: str,
        aggregation: str = "Zone Weighted",
    ) -> dict[str, float] | None:
        """Load HeatIndexCategories summary for stacked bar. Override for support."""
        return None

    def get_overheating_thresholds(self, run_id: str) -> list[float]:
        """Get available heat thresholds for a run. Override for support."""
        return [26.0, 30.0, 35.0]

    def load_overheating_summary(
        self,
        run_id: str,
        aggregation: str = "Zone Weighted",
    ) -> pd.DataFrame | None:
        """Load summary stats across all buildings for heatmap. Override for support."""
        return None

    def load_overheating_threshold_curves(
        self,
        run_id: str,
        aggregation: str = "Zone Weighted",
        data_source_type: str = "BasicOverheating",
    ) -> pd.DataFrame | None:
        """Mean/median and fraction nonzero vs temperature threshold. Override for support."""
        return None

    def resolve_run_dir(self, run_id: str) -> Path | None:
        """Local run directory path for loading parquet helpers. Override for local sources."""
        return None

    @classmethod
    def from_config(cls, config: DataSourceConfig) -> DataSource:
        """Factory method to create appropriate data source."""
        if isinstance(config, LocalDataSourceConfig):
            return LocalDataSource(config)
        elif isinstance(config, S3DataSourceConfig):
            return S3DataSource(config)
        msg = f"Unknown config type: {type(config)}"
        raise ValueError(msg)


class LocalDataSource(DataSource):
    """Data source for locally stored parquet files."""

    def __init__(self, config: LocalDataSourceConfig) -> None:
        """Init class for local data source."""
        self.config = config
        self._run_dirs: dict[str, Path] = {}

    def list_available_runs(self) -> list[str]:
        """List available run directories."""
        run_dirs = find_output_run_dirs(self.config.base_dir)
        self._run_dirs = {str(d.relative_to(self.config.base_dir)): d for d in run_dirs}
        return list(self._run_dirs.keys())

    def get_run_parquet_path(self, run_id: str) -> Path:
        """Resolved EnergyAndPeak / Results parquet path for a run (for cache keys)."""
        if run_id not in self._run_dirs:
            self.list_available_runs()

        run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            msg = f"Run not found: {run_id}"
            raise ValueError(msg)

        pq_file = get_pq_file_for_run(run_dir)
        if pq_file is None:
            msg = f"No .pq file in {run_dir}"
            raise FileNotFoundError(msg)
        return pq_file

    def load_run_data(self, run_id: str) -> pd.DataFrame:
        """Load parquet data for a run."""
        pq_file = self.get_run_parquet_path(run_id)
        return load_output_table(pq_file)

    def load_building_locations(self) -> pd.DataFrame | None:
        """Load building locations from the configured inputs path (default ``inputs/buildings.parquet``).

        Used when run-local ``buildings.parquet`` is absent; see
        ``resolve_buildings_df_for_overheating_plots`` in ``utils``.
        """
        buildings_path = self.config.buildings_path or Path("inputs/buildings.parquet")
        if not buildings_path.exists():
            return None

        gdf = read_geo_file(buildings_path)

        if "lat" in gdf.columns and "lon" in gdf.columns:
            gdf["lat"] = gdf["lat"].astype("float64")
            gdf["lon"] = gdf["lon"].astype("float64")
        else:
            centroids = gdf.geometry.centroid
            gdf["lat"] = centroids.y.astype("float64")
            gdf["lon"] = centroids.x.astype("float64")

        return pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))

    def list_runs_with_overheating(self) -> list[str]:
        """List run ids that have any overheating output."""
        self.list_available_runs()
        return [rid for rid, d in self._run_dirs.items() if run_has_overheating(d)]

    def list_overheating_files(self, run_id: str) -> list[str]:
        """List available overheating df keys for a run."""
        run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            self.list_available_runs()
            run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            return []
        return list_overheating_files_for_run(run_dir)

    def load_overheating_map_data(
        self,
        run_id: str,
        cart_crs: str = "EPSG:3857",
        heat_threshold_c: float = 26.0,
        aggregation: str = "Zone Weighted",
        data_source_type: str = "BasicOverheating",
        heat_index_metric: str = "danger_hours",
    ) -> pd.DataFrame | None:
        """Load map-ready overheating data (geometry + selected metric)."""
        run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            self.list_available_runs()
            run_dir = self._run_dirs.get(run_id)
        if run_dir is None or not run_has_overheating(run_dir):
            return None
        return build_overheating_map_df(
            run_dir,
            cart_crs=cart_crs,
            heat_threshold_c=heat_threshold_c,
            aggregation=aggregation,
            data_source_type=data_source_type,
            heat_index_metric=heat_index_metric,
        )

    def load_overheating_heat_index_summary(
        self,
        run_id: str,
        aggregation: str = "Zone Weighted",
    ) -> dict[str, float] | None:
        """Load HeatIndexCategories summary (hours by category) for stacked bar chart."""
        run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            self.list_available_runs()
            run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            return None
        return load_heat_index_summary_for_chart(run_dir, aggregation=aggregation)

    def get_overheating_thresholds(self, run_id: str) -> list[float]:
        """Get available heat thresholds from the data."""
        run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            self.list_available_runs()
            run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            return [26.0, 30.0, 35.0]
        return get_overheating_thresholds(run_dir)

    def load_overheating_summary(
        self,
        run_id: str,
        aggregation: str = "Zone Weighted",
    ) -> pd.DataFrame | None:
        """Load summary stats across all buildings for heatmap."""
        run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            self.list_available_runs()
            run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            return None
        return build_overheating_summary_df(run_dir, aggregation=aggregation)

    def load_overheating_threshold_curves(
        self,
        run_id: str,
        aggregation: str = "Zone Weighted",
        data_source_type: str = "BasicOverheating",
    ) -> pd.DataFrame | None:
        """Per-threshold stats for BasicOverheating / ExceedanceDegreeHours."""
        run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            self.list_available_runs()
            run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            return None
        return build_overheating_threshold_curves_df(
            run_dir,
            aggregation=aggregation,
            data_source_type=data_source_type,
        )

    def resolve_run_dir(self, run_id: str) -> Path | None:
        """Return absolute path to a run output directory."""
        run_dir = self._run_dirs.get(run_id)
        if run_dir is None:
            self.list_available_runs()
            run_dir = self._run_dirs.get(run_id)
        return run_dir


class S3DataSource(LocalDataSource):
    """Experiments in the scythe storage bucket (AWS, or LocalStack via AWS_ENDPOINT_URL).

    Run ids mirror the local layout ("<experiment>/<run>/vX.Y.Z"); the latest
    timestamped run of a version is used. A run's final result files are
    downloaded into cache_dir/<run id>/ the first time it is opened, and from then
    on every LocalDataSource method (overheating loaders included) reads that copy.
    """

    def __init__(self, config: S3DataSourceConfig) -> None:
        """Init class for S3 data source."""
        super().__init__(LocalDataSourceConfig(base_dir=config.cache_dir))
        self.s3_config = config
        self._client: S3Client | None = None
        self._settings = ScytheStorageSettings()

    @property
    def client(self) -> S3Client:
        """Lazy-load S3 client."""
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client

    @property
    def _prefix(self) -> str:
        return self._settings.BUCKET_PREFIX.rstrip("/") + "/"

    def list_available_runs(self) -> list[str]:
        """List every experiment version in the bucket."""
        return self._list_available_runs_cached()

    @functools.lru_cache(maxsize=1)  # noqa: B019 - one instance per config, refreshed via the sidebar
    def _list_available_runs_cached(self) -> list[str]:
        runs = list_s3_runs(self.client, self._settings.BUCKET, self._prefix)
        self._run_dirs = {r: self.config.base_dir / r for r in runs}
        return runs

    @functools.lru_cache(maxsize=256)  # noqa: B019
    def _final_files(self, run_id: str) -> dict[str, tuple[str, int]]:
        """Stem -> (key, size) of the final result files of the latest run of a version."""
        timestamps = _get_s3_prefixes(
            self.client, self._settings.BUCKET, f"{self._prefix}{run_id}/"
        )
        if not timestamps:
            return {}
        # timestamp folders are YYYY-MM-DD_HH-MM-SS, so the max string is the latest
        final = f"{max(timestamps)}final/"
        files: dict[str, tuple[str, int]] = {}
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._settings.BUCKET, Prefix=final):
            for obj in page.get("Contents", []):
                key = obj.get("Key", "")
                if key.endswith((".pq", ".parquet")):
                    files[Path(key).stem] = (key, int(obj.get("Size", 0)))
        return files

    @functools.lru_cache(maxsize=256)  # noqa: B019
    def _sync(self, run_id: str) -> Path:
        """Download the run's result files into cache_dir unless an identical-size copy is there."""
        files = self._final_files(run_id)
        main = next((s for s in _S3_RESULT_STEMS if s in files), None)
        if main is None:
            msg = f"No results found for {run_id}."
            raise FileNotFoundError(msg)
        run_dir = self.config.base_dir / run_id
        for stem in (main, *(s for s in _S3_OVERHEATING_STEMS if s in files)):
            key, size = files[stem]
            dest = run_dir / Path(key).name
            if dest.is_file() and dest.stat().st_size == size:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(
                Bucket=self._settings.BUCKET, Key=key, Filename=dest.as_posix()
            )
        self._run_dirs[run_id] = run_dir
        return run_dir

    # every run-specific read goes through the local copy, downloaded on first use
    def get_run_parquet_path(self, run_id: str) -> Path:
        """Download the run if needed, then return its local parquet path."""
        self._sync(run_id)
        return super().get_run_parquet_path(run_id)

    def resolve_run_dir(self, run_id: str) -> Path | None:
        """Download the run if needed, then return its local folder."""
        return self._sync(run_id)

    def list_runs_with_overheating(self) -> list[str]:
        """List run ids whose final results include an overheating table."""
        return [
            r
            for r in self.list_available_runs()
            if any(s in self._final_files(r) for s in _S3_OVERHEATING_STEMS)
        ]

    def list_overheating_files(self, run_id: str) -> list[str]:
        """Overheating tables of the run (downloaded on first use)."""
        self._sync(run_id)
        return super().list_overheating_files(run_id)

    def load_overheating_map_data(self, run_id: str, *args, **kwargs):  # noqa: D102
        self._sync(run_id)
        return super().load_overheating_map_data(run_id, *args, **kwargs)

    def load_overheating_heat_index_summary(self, run_id: str, *args, **kwargs):  # noqa: D102
        self._sync(run_id)
        return super().load_overheating_heat_index_summary(run_id, *args, **kwargs)

    def get_overheating_thresholds(self, run_id: str) -> list[float]:  # noqa: D102
        self._sync(run_id)
        return super().get_overheating_thresholds(run_id)

    def load_overheating_summary(self, run_id: str, *args, **kwargs):  # noqa: D102
        self._sync(run_id)
        return super().load_overheating_summary(run_id, *args, **kwargs)

    def load_overheating_threshold_curves(self, run_id: str, *args, **kwargs):  # noqa: D102
        self._sync(run_id)
        return super().load_overheating_threshold_curves(run_id, *args, **kwargs)

    def load_building_locations(self) -> pd.DataFrame | None:
        """S3 source doesn't have local building locations by default."""
        return None
