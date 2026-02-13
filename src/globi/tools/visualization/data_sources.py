"""Data source abstraction for local and S3 data loading."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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


@dataclass
class S3ExperimentInfo:
    """Information about an experiment available in S3."""

    run_name: str
    versions: list[str]
    latest_version: str | None = None

    @property
    def display_name(self) -> str:
        """Display name for the experiment."""
        return self.run_name

    def __str__(self) -> str:
        """String representation."""
        version_str = self.latest_version or "no versions"
        return f"{self.run_name} ({version_str})"


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


def _extract_experiment_names(prefixes: list[str], base_prefix: str) -> list[str]:
    """Extract experiment names from S3 prefixes."""
    names = []
    for p in prefixes:
        name = p[len(base_prefix) :].rstrip("/")
        if name:
            names.append(name)
    return names


def _extract_versions(prefixes: list[str], exp_prefix: str) -> list[str]:
    """Extract version strings from S3 prefixes."""
    versions = []
    for p in prefixes:
        version = p[len(exp_prefix) :].rstrip("/")
        if version.startswith("v"):
            versions.append(version)
    return versions


def list_s3_experiments(
    bucket: str | None = None,
    prefix: str | None = None,
    s3_client: S3Client | None = None,
) -> list[S3ExperimentInfo]:
    """List all available experiments in S3.

    Args:
        bucket: S3 bucket name. If None, uses ScytheStorageSettings.
        prefix: S3 prefix. If None, uses ScytheStorageSettings.BUCKET_PREFIX.
        s3_client: Optional S3 client. If None, creates a new one.

    Returns:
        List of S3ExperimentInfo objects with experiment names and versions.
    """
    import boto3
    from scythe.settings import ScytheStorageSettings

    settings = ScytheStorageSettings()
    bucket = bucket or settings.BUCKET
    prefix = prefix or settings.BUCKET_PREFIX

    if s3_client is None:
        s3_client = boto3.client("s3")

    if not prefix.endswith("/"):
        prefix = prefix + "/"

    exp_prefixes = _get_s3_prefixes(s3_client, bucket, prefix)
    exp_names = _extract_experiment_names(exp_prefixes, prefix)

    result = []
    for exp_name in sorted(exp_names):
        exp_prefix = f"{prefix}{exp_name}/"
        version_prefixes = _get_s3_prefixes(s3_client, bucket, exp_prefix)
        versions = _extract_versions(version_prefixes, exp_prefix)
        sorted_versions = _sort_versions(versions)
        latest = sorted_versions[-1] if sorted_versions else None
        result.append(
            S3ExperimentInfo(
                run_name=exp_name,
                versions=sorted_versions,
                latest_version=latest,
            )
        )
    return result


def _sort_versions(versions: list[str]) -> list[str]:
    """Sort semantic versions in ascending order."""

    def parse_version(v: str) -> tuple[int, int, int]:
        if v.startswith("v"):
            v = v[1:]
        parts = v.replace("-", ".").split(".")
        return (
            int(parts[0]) if len(parts) > 0 else 0,
            int(parts[1]) if len(parts) > 1 else 0,
            int(parts[2]) if len(parts) > 2 else 0,
        )

    return sorted(versions, key=parse_version)


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
