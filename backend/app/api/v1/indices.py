
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.index import (
    IndexCreate,
    IndexRead,
    IndexStatusUpdate,
    IndexUpdate,
)
from app.services import index_service


router = APIRouter(
    prefix="/indices",
    tags=["Index Registry"],
)


@router.get("", response_model=list[IndexRead])
def get_indices(
    active_only: bool = False,
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return index_service.list_indices(
        db=db,
        active_only=active_only,
        category=category,
    )


@router.get("/{index_id}", response_model=IndexRead)
def get_index(
    index_id: int,
    db: Session = Depends(get_db),
):
    index = index_service.get_index(db, index_id)

    if index is None:
        raise HTTPException(
            status_code=404,
            detail="Index not found.",
        )

    return index


@router.post(
    "",
    response_model=IndexRead,
    status_code=status.HTTP_201_CREATED,
)
def add_index(
    data: IndexCreate,
    db: Session = Depends(get_db),
):
    try:
        return index_service.create_index(db, data)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="An index with this code already exists.",
        )


@router.patch("/{index_id}", response_model=IndexRead)
def edit_index(
    index_id: int,
    data: IndexUpdate,
    db: Session = Depends(get_db),
):
    index = index_service.get_index(db, index_id)

    if index is None:
        raise HTTPException(
            status_code=404,
            detail="Index not found.",
        )

    try:
        return index_service.update_index(db, index, data)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=400,
            detail="Unable to update index.",
        )


@router.patch(
    "/{index_id}/status",
    response_model=IndexRead,
)
def change_index_status(
    index_id: int,
    data: IndexStatusUpdate,
    db: Session = Depends(get_db),
):
    index = index_service.get_index(db, index_id)

    if index is None:
        raise HTTPException(
            status_code=404,
            detail="Index not found.",
        )

    return index_service.update_index_status(
        db,
        index,
        data.is_active,
    )
