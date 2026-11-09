
from logging.config import fileConfig

from alembic import context

from app.core.database import Base, engine
from app.models.index import Index, IndexProviderMapping  # noqa: F401
import app.models.historical  # noqa: F401

config = context.config

# Configure Alembic logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Register existing SQLAlchemy models for migration generation.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate migration SQL without opening a database connection."""

    context.configure(
        url=engine.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using the configured SQLAlchemy engine."""

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
