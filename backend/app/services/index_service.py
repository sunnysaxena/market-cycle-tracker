
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.index import Index
from app.schemas.index import IndexCreate, IndexUpdate


def list_indices(
    db: Session,
    active_only: bool = False,
    category: str | None = None,
) -> list[Index]:

    statement = select(Index)

    if active_only:
        statement = statement.where(Index.is_active.is_(True))

    if category:
        statement = statement.where(Index.category == category)

    statement = statement.order_by(
        Index.display_order,
        Index.name,
    )

    return list(db.scalars(statement).all())


def get_index(db: Session, index_id: int) -> Index | None:
    return db.get(Index, index_id)


def create_index(db: Session, data: IndexCreate) -> Index:
    index = Index(**data.model_dump())

    db.add(index)
    db.commit()
    db.refresh(index)

    return index


def update_index(
    db: Session,
    index: Index,
    data: IndexUpdate,
) -> Index:

    updates = data.model_dump(exclude_unset=True)

    for field, value in updates.items():
        setattr(index, field, value)

    db.commit()
    db.refresh(index)

    return index


def update_index_status(
    db: Session,
    index: Index,
    is_active: bool,
) -> Index:

    index.is_active = is_active

    db.commit()
    db.refresh(index)

    return index
