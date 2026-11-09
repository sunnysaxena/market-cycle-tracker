
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class BatchMetadata(BaseModel):
    """Metadata identifying the historical import batch used by an API response."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )

    import_batch_id: int = Field(validation_alias="id")
    status: str
    imported_rows: int
    imported_at_utc: datetime | None


class PaginationMetadata(BaseModel):
    """Pagination details for list-based API responses."""

    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    total_records: int | None = Field(default=None, ge=0)


class DataAvailability(BaseModel):
    """Describes the availability of data for a requested resource."""

    status: str
    is_available: bool
    record_count: int = Field(default=0, ge=0)
    latest_date: date | None = None
    message: str | None = None


class APIErrorDetail(BaseModel):
    """Standard API error details."""

    code: str
    message: str


class APIErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: APIErrorDetail
