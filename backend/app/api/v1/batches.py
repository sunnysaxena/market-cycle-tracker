from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.batches import BatchListResponse
from app.schemas.common import PaginationMetadata
from app.services.batch_service import list_import_batches


router = APIRouter(
    prefix="/batches",
    tags=["Historical Batches"],
)


@router.get(
    "",
    response_model=BatchListResponse,
)
def read_import_batches(
    completed_only: bool = True,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    records, total_records = list_import_batches(
        db,
        completed_only=completed_only,
        limit=limit,
        offset=offset,
    )

    return BatchListResponse(
        batches=records,
        pagination=PaginationMetadata(
            limit=limit,
            offset=offset,
            returned_count=len(records),
            total_records=total_records,
        ),
    )
