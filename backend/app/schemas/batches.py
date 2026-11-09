from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import PaginationMetadata


class BatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    imported_rows: int
    imported_at_utc: datetime | None = None


class BatchListResponse(BaseModel):
    batches: list[BatchRead]
    pagination: PaginationMetadata
