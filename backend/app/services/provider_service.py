
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.index import IndexProviderMapping
from app.schemas.provider import (
    ProviderMappingCreate,
    ProviderMappingUpdate,
)


def list_mappings(
    db: Session,
    index_id: int,
) -> list[IndexProviderMapping]:

    statement = (
        select(IndexProviderMapping)
        .where(IndexProviderMapping.index_id == index_id)
        .order_by(IndexProviderMapping.provider_name)
    )

    return list(db.scalars(statement).all())


def get_mapping(
    db: Session,
    index_id: int,
    mapping_id: int,
) -> IndexProviderMapping | None:

    statement = select(IndexProviderMapping).where(
        IndexProviderMapping.id == mapping_id,
        IndexProviderMapping.index_id == index_id,
    )

    return db.scalar(statement)


def create_mapping(
    db: Session,
    index_id: int,
    data: ProviderMappingCreate,
) -> IndexProviderMapping:

    mapping = IndexProviderMapping(
        index_id=index_id,
        **data.model_dump(),
    )

    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    return mapping


def update_mapping(
    db: Session,
    mapping: IndexProviderMapping,
    data: ProviderMappingUpdate,
) -> IndexProviderMapping:

    updates = data.model_dump(exclude_unset=True)

    for field, value in updates.items():
        setattr(mapping, field, value)

    db.commit()
    db.refresh(mapping)

    return mapping


def update_mapping_status(
    db: Session,
    mapping: IndexProviderMapping,
    is_active: bool,
) -> IndexProviderMapping:

    mapping.is_active = is_active

    db.commit()
    db.refresh(mapping)

    return mapping


def delete_mapping(
    db: Session,
    mapping: IndexProviderMapping,
) -> None:
    db.delete(mapping)
    db.commit()
