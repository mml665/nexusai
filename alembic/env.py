"""Alembic environment configuration for NexusAI."""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use DATABASE_URL from environment if available
import os
db_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
# Convert asyncpg URL to psycopg2 URL for Alembic
if db_url and "postgresql://" in db_url:
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://")
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = None


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
