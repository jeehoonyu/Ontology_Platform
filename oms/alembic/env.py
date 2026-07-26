from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool, text

os.environ["SKIP_CREATE_ALL"] = "1"
from app.main import models  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = models.Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            if connection.dialect.name == "postgresql":
                # All API replicas run the same entrypoint. Serialize migration DDL
                # inside the transaction so only one replica can advance the schema.
                connection.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": 781230947125})
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
