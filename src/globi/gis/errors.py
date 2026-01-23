"""Errors for GIS preprocessor."""


class GISPreprocessorError(Exception):
    """Exception for GIS preprocessor errors."""


class GISFileHasNoFeaturesError(GISPreprocessorError):
    """Exception for when a GIS file has no features."""

    def __init__(self):
        """Initialize the GIS file has no features error."""
        super().__init__("GIS data contains no features.")


class GISFileHasInvalidCategoricalSemanticFieldError(GISPreprocessorError):
    """Exception for when a GIS file has invalid categorical semantic fields."""

    def __init__(self, field_name: str, invalid_values: list[str], options: list[str]):
        """Initialize the GIS file has invalid semantic field error."""
        self.field_name = field_name
        self.invalid_values = invalid_values
        self.options = options
        printable_invalid_values = (
            [*invalid_values[:5], "..."] if len(invalid_values) > 5 else invalid_values
        )
        super().__init__(
            f"Field '{field_name}' has values which are not in the allowed options: "
            f"{printable_invalid_values}. Allowed options: {options}"
        )


class GISFileHasOutOfBoundsNumericSemanticFieldError(GISPreprocessorError):
    """Exception for when a GIS file has out of bounds numeric semantic fields."""

    def __init__(
        self, field_name: str, values: list[float], min_val: float, max_val: float
    ):
        """Initialize the GIS file has out of bounds numeric semantic field error."""
        self.field_name = field_name
        self.values = values
        self.min_val = min_val
        self.max_val = max_val
        printable_values = [*values[:5], "..."] if len(values) > 5 else values
        super().__init__(
            f"Field '{field_name}' has values which are out of bounds: {printable_values}. "
            f"Allowed values: {min_val} to {max_val}"
        )


class GISFileHasSemanticFieldWithNoValidatorError(GISPreprocessorError):
    """Exception for when a GIS file has a semantic field with no validator."""

    def __init__(self, field_name: str):
        """Initialize the GIS file has semantic field with no validator error."""
        self.field_name = field_name
        super().__init__(f"Field '{field_name}' has no validator.")


class GISFileHasMissingColumnsError(GISPreprocessorError):
    """Exception for when a GIS file has missing columns."""

    def __init__(self, missing_cols: list[str], available_cols: list[str]):
        """Initialize the GIS file has missing columns error."""
        self.missing_cols = missing_cols
        self.available_cols = available_cols
        super().__init__(
            f"GIS file has missing columns: {missing_cols}. Available columns: {available_cols}"
        )


class GISFileHasNoCRSError(GISPreprocessorError):
    """Exception for when a GIS file has no CRS."""

    def __init__(self):
        """Initialize the GIS file has no CRS error."""
        super().__init__(
            "GIS file has no crs.  Please set the CRS before running this script."
        )


class GISFileHasUnexpectedCRSError(GISPreprocessorError):
    """Exception for when a GIS file has an unexpected CRS."""

    def __init__(self, expected_crs: str, actual_crs: str, allow_mercator: bool = True):
        """Initialize the GIS file has unexpected CRS error."""
        self.expected_crs = expected_crs
        self.actual_crs = actual_crs
        self.allow_mercator = allow_mercator
        printable_crs = {"EPSG:4326"}
        if allow_mercator:
            printable_crs.add("EPSG:3857")
        printable_crs.add(expected_crs)
        super().__init__(
            f"GIS file has unexpected CRS: {actual_crs}. Expected CRS: {list(printable_crs)}.  Please update the CRS to one of the expected values before running this script."
        )


class GISFileMissingBothHeightAndFloorsError(GISPreprocessorError):
    """Exception for when a GIS file is missing both height and floors."""

    def __init__(self):
        """Initialize the GIS file missing both height and floors error."""
        super().__init__("GIS file is missing both height and floors.")


class GISFileHasNonNumericHeightError(GISPreprocessorError):
    """Exception for when a GIS file has a non-numeric height."""

    def __init__(self, height_col: str):
        """Initialize the GIS file has non-numeric height error."""
        self.height_col = height_col
        super().__init__(f"GIS file has a non-numeric height column: {height_col}.")


class GISFileHasNonNumericFloorsError(GISPreprocessorError):
    """Exception for when a GIS file has a non-numeric floors column."""

    def __init__(self, nfloors_col: str):
        """Initialize the GIS file has non-numeric floors error."""
        self.nfloors_col = nfloors_col
        super().__init__(f"GIS file has a non-numeric floors column: {nfloors_col}.")


class SemanticFieldsFileHasNoBuildingIDColumnError(GISPreprocessorError):
    """Exception for when a semantic fields file has no building ID column."""

    def __init__(self):
        """Initialize the semantic fields file has no building ID column error."""
        super().__init__("Semantic fields file is missing a building ID column.")


class GISFileHasNoBuildingIDColumnError(GISPreprocessorError):
    """Exception for when a GIS file has no building ID column."""

    def __init__(self):
        """Initialize the GIS file has no building ID column error."""
        super().__init__("GIS file is missing a building ID column.")


class GISFileHasMissingBuildingIDsError(GISPreprocessorError):
    """Exception for when a GIS file has missing building IDs."""

    def __init__(self):
        """Initialize the GIS file has missing building IDs error."""
        super().__init__("GIS file is missing building ID in some rows.")


class GISFileHasNonUniqueBuildingIDsError(GISPreprocessorError):
    """Exception for when a GIS file has non-unique building IDs."""

    def __init__(self):
        """Initialize the GIS file has non-unique building IDs error."""
        super().__init__("GIS file has non-unique building IDs.")
