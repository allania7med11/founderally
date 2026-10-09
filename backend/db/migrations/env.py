"""Alembic entry point: the same models and DATABASE_URL as the app, a sync engine for the migration itself."""

from alembic import context
from sqlalchemy import create_engine

from db.models import Base
from settings import settings

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
