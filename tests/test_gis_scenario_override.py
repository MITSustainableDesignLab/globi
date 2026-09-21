"""Regression tests for GIS scenario overrides."""

from pathlib import Path

from globi.models.configs import DeterministicGISPreprocessorConfig, FileConfig
from globi.pipelines.gis import preprocess_gis_file

DATA_DIR = Path(__file__).parent / "data" / "e2e"


def test_preprocess_scenario_override_uses_semantic_field_casing() -> None:
    """Scenario overrides are written to uppercase semantic fields."""
    file_config = FileConfig(
        gis_file=DATA_DIR / "buildings.geojson",
        db_file=DATA_DIR / "components-lib.db",
        semantic_fields_file=DATA_DIR / "semantic-fields.yml",
        epwzip_file="https://example.com/weather.zip",
        component_map_file=DATA_DIR / "component-map.yml",
    )
    config = DeterministicGISPreprocessorConfig.from_(
        DATA_DIR / "gis-preprocessor.yml"
    )

    gdf, colmap = preprocess_gis_file(
        config,
        file_config,
        scenario="Retrofit",
    )

    contexts = gdf[colmap.Semantic_Field_Context_col]
    assert set(gdf["Scenario"].unique()) == {"Retrofit"}
    assert {context["Scenario"] for context in contexts} == {"Retrofit"}
