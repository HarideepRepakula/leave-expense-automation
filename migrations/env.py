"""Alembic environment. URL precedence: ALEMBIC_DATABASE_URL env var, then DATABASE_URL from .env."""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from src.models import Base, GroundTruthBase  # registers all tables

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

load_dotenv()
_url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not _url:
    raise RuntimeError("Set DATABASE_URL in .env (see .env.example) or ALEMBIC_DATABASE_URL in the environment.")
# Escape % for configparser interpolation (passwords may contain it).
config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))

target_metadata = [Base.metadata, GroundTruthBase.metadata]


def run_migrations_offline() -> None:
    context.configure(
        url=_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
