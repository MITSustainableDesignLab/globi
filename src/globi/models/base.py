"""Base models for the GloBI project."""

import tempfile
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel
from scythe.utils.filesys import FileReference, fetch_uri


class BaseConfig(BaseModel):
    """A base configuration for a Globi experiment."""

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> Self:
        """Load the base configuration from a manifest file."""
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
        return cls.model_validate(manifest)

    @classmethod
    def from_manifest_fileref(cls, manifest_fileref: FileReference) -> Self:
        """Load the base configuration from a manifest file reference."""
        if isinstance(manifest_fileref, str) and (
            not manifest_fileref.startswith("http://")
            and not manifest_fileref.startswith("https://")
            and not manifest_fileref.startswith("s3://")
        ):
            manifest_fileref = Path(manifest_fileref)
        if isinstance(manifest_fileref, Path):
            local_path = manifest_fileref
        else:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir) / "manifest.yaml"
                local_path = fetch_uri(manifest_fileref, temp_path)
        return cls.from_manifest(local_path)

    @classmethod
    def from_(cls, v: Self | FileReference) -> Self:
        """Load the base configuration from a manifest file reference or a local path."""
        if isinstance(v, BaseConfig | dict):
            return v
        return cls.from_manifest_fileref(v)
