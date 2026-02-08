"""Data source abstraction for local and S3 data loading."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from globi.tools.visualization.models import (
    DataSourceConfig,
    LocalDataSourceConfig,
    S3DataSourceConfig,
)
from globi.tools.visualization.utils import (
    find_output_run_dirs,
    get_pq_file_for_run,
    load_output_table,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


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
        """Load building location data if available."""
        ...

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

    def load_run_data(self, run_id: str) -> pd.DataFrame:
        """Load parquet data for a run."""
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

        return load_output_table(pq_file)

    def load_building_locations(self) -> pd.DataFrame | None:
        """Load building locations from inputs/buildings.parquet."""
        buildings_path = self.config.buildings_path or Path("inputs/buildings.parquet")
        if not buildings_path.exists():
            return None

        import geopandas as gpd

        gdf = gpd.read_file(buildings_path)

        if "lat" in gdf.columns and "lon" in gdf.columns:
            gdf["lat"] = gdf["lat"].astype("float64")
            gdf["lon"] = gdf["lon"].astype("float64")
        else:
            centroids = gdf.geometry.centroid
            gdf["lat"] = centroids.y.astype("float64")
            gdf["lon"] = centroids.x.astype("float64")

        return pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))


class S3DataSource(DataSource):
    """Data source for S3-stored experiment results."""

    def __init__(self, config: S3DataSourceConfig) -> None:
        """Init class for S3 data source."""
        self.config = config
        self._client: S3Client | None = None
        self._cached_path: Path | None = None

    @property
    def client(self) -> S3Client:
        """Lazy-load S3 client."""
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client

    def list_available_runs(self) -> list[str]:
        """For S3, return the configured run name."""
        return [self.config.run_name]

    def load_run_data(self, run_id: str) -> pd.DataFrame:
        """Download and load data from S3."""
        from scythe.experiments import BaseExperiment, SemVer
        from scythe.settings import ScytheStorageSettings

        from globi.pipelines import simulate_globi_building

        s3_settings = ScytheStorageSettings()
        exp = BaseExperiment(
            experiment=simulate_globi_building,
            run_name=self.config.run_name,
        )

        if self.config.version:
            sem_version = SemVer.FromString(self.config.version)
        else:
            exp_version = exp.latest_version(self.client, from_cache=False)
            if exp_version is None:
                msg = f"No version found for {self.config.run_name}"
                raise ValueError(msg)
            sem_version = exp_version.version

        results_filekeys = exp.latest_results_for_version(sem_version)
        if self.config.dataframe_key not in results_filekeys:
            msg = f"Key {self.config.dataframe_key} not found"
            raise ValueError(msg)

        output_path = (
            self.config.cache_dir
            / self.config.run_name
            / str(sem_version)
            / f"{self.config.dataframe_key}.pq"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.client.download_file(
            Bucket=s3_settings.BUCKET,
            Key=results_filekeys[self.config.dataframe_key],
            Filename=str(output_path),
        )

        self._cached_path = output_path
        return pd.read_parquet(output_path)

    def load_building_locations(self) -> pd.DataFrame | None:
        """S3 source doesn't have local building locations by default."""
        return None
