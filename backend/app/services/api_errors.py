class APIServiceError(Exception):
    """Base exception for API service failures."""

    status_code = 500
    error_code = "API_SERVICE_ERROR"


class InstrumentNotFoundError(APIServiceError):
    """Raised when an instrument is unknown or inactive."""

    status_code = 404
    error_code = "INSTRUMENT_NOT_FOUND"

class UnsupportedInstrumentCategoryError(APIServiceError):
    """Raised when an instrument category is unsupported by an API."""

    status_code = 422
    error_code = "UNSUPPORTED_INSTRUMENT_CATEGORY"

