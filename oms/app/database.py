from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./oms.db")

_sqlite = DATABASE_URL.startswith("sqlite")
_engine_options = {
    "connect_args": {"check_same_thread": False, "timeout": 30} if _sqlite else {},
    "pool_pre_ping": True,
    "pool_size": int(os.getenv("DATABASE_POOL_SIZE", "25")),
    "max_overflow": int(os.getenv("DATABASE_MAX_OVERFLOW", "25")),
    "pool_timeout": int(os.getenv("DATABASE_POOL_TIMEOUT_SECONDS", "30")),
}

engine = create_engine(DATABASE_URL, **_engine_options)


if _sqlite:
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
