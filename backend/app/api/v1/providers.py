
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import index_service, provider_service
from app.schemas.provider import (
    ProviderMappingCreate,
    ProviderMappingRead,
    ProviderMappingUpdate,
    ProviderMappingStatusUpdate,
)

from fastapi import APIRouter, Depends, HTTPException, Response, status

router = APIRouter(
    prefix="/indices/{index_id}/providers",
    tags=["Provider Mapping"],
)


def verify_index(db: Session, index_id: int):
    index = index_service.get_index(db, index_id)

    if index is None:
        raise HTTPException(
            status_code=404,
            detail="Index not found.",
        )

    return index


@router.get("", response_model=list[ProviderMappingRead])
def get_mappings(
    index_id: int,
    db: Session = Depends(get_db),
):
    verify_index(db, index_id)

    return provider_service.list_mappings(db, index_id)


@router.post(
    "",
    response_model=ProviderMappingRead,
    status_code=status.HTTP_201_CREATED,
)
def add_mapping(
    index_id: int,
    data: ProviderMappingCreate,
    db: Session = Depends(get_db),
):
    verify_index(db, index_id)

    try:
        return provider_service.create_mapping(
            db,
            index_id,
            data,
        )

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="This provider is already mapped to the index.",
        )


@router.patch(
    "/{mapping_id}",
    response_model=ProviderMappingRead,
)
def edit_mapping(
    index_id: int,
    mapping_id: int,
    data: ProviderMappingUpdate,
    db: Session = Depends(get_db),
):
    verify_index(db, index_id)

    mapping = provider_service.get_mapping(
        db,
        index_id,
        mapping_id,
    )

    if mapping is None:
        raise HTTPException(
            status_code=404,
            detail="Provider mapping not found.",
        )

    try:
        return provider_service.update_mapping(
            db,
            mapping,
            data,
        )

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="This provider mapping already exists.",
        )


@router.patch(
    "/{mapping_id}/status",
    response_model=ProviderMappingRead,
)
def change_mapping_status(
    index_id: int,
    mapping_id: int,
    data: ProviderMappingStatusUpdate,
    db: Session = Depends(get_db),
):
    verify_index(db, index_id)

    mapping = provider_service.get_mapping(
        db,
        index_id,
        mapping_id,
    )

    if mapping is None:
        raise HTTPException(
            status_code=404,
            detail="Provider mapping not found.",
        )

    return provider_service.update_mapping_status(
        db,
        mapping,
        data.is_active,
    )


@router.delete(
    "/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_provider_mapping(
    index_id: int,
    mapping_id: int,
    db: Session = Depends(get_db),
):
    verify_index(db, index_id)

    mapping = provider_service.get_mapping(
        db,
        index_id,
        mapping_id,
    )

    if mapping is None:
        raise HTTPException(
            status_code=404,
            detail="Provider mapping not found.",
        )

    if mapping.is_active:
        raise HTTPException(
            status_code=409,
            detail="Disable the provider mapping before deleting it.",
        )

    provider_service.delete_mapping(db, mapping)

    return Response(status_code=204)
