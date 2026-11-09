from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.historical import HistoricalSnapshot
from app.services.api_errors import APIServiceError

class BatchResolutionError(APIServiceError):
    """Base exception for historical batch resolution failures."""

    status_code = 500
    error_code = "BATCH_RESOLUTION_ERROR"


class BatchNotFoundError(BatchResolutionError):
    """Raised when an explicitly requested batch does not exist."""

    status_code = 404
    error_code = "BATCH_NOT_FOUND"


class BatchNotCompletedError(BatchResolutionError):
    """Raised when an explicitly requested batch is not completed."""

    status_code = 409
    error_code = "BATCH_NOT_COMPLETED"


class NoCompletedBatchError(BatchResolutionError):
    """Raised when no completed historical batch is available."""

    status_code = 409
    error_code = "NO_COMPLETED_BATCH"


class NoCompletedBatchError(BatchResolutionError):
    """Raised when no completed historical batch is available."""

    status_code = 409


def resolve_import_batch(
    db: Session,
    import_batch_id: int | None = None,
) -> HistoricalSnapshot:
    """
    Resolve a usable historical import batch.

    If import_batch_id is omitted, select the latest completed batch.
    If it is supplied, validate and return that exact batch.

    This function is read-only and does not commit or modify the session.
    """

    if import_batch_id is not None:
        if (
            isinstance(import_batch_id, bool)
            or not isinstance(import_batch_id, int)
            or import_batch_id <= 0
        ):
            raise ValueError("import_batch_id must be a positive integer.")

        batch = db.get(HistoricalSnapshot, import_batch_id)

        if batch is None:
            raise BatchNotFoundError(
                f"Historical import batch {import_batch_id} was not found."
            )

        if (batch.status or "").strip().lower() != "completed":
            raise BatchNotCompletedError(
                f"Historical import batch {import_batch_id} "
                f"is not completed (status: {batch.status})."
            )

        return batch

    statement = (
        select(HistoricalSnapshot)
        .where(
            func.lower(func.trim(HistoricalSnapshot.status)) == "completed"
        )
        .order_by(
            HistoricalSnapshot.imported_at_utc.desc().nulls_last(),
            HistoricalSnapshot.id.desc(),
        )
        .limit(1)
    )

    batch = db.execute(statement).scalar_one_or_none()

    if batch is None:
        raise NoCompletedBatchError(
            "No completed historical import batch is available."
        )

    return batch


    
