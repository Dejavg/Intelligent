from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
UPLOAD_DIR = PROJECT_ROOT / "backend" / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR / 'seewo_smartgrade.db'}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    """Tiny SQLite migration helper for demo schema upgrades."""

    additions = {
        "submissions": {
            "ocr_engine": "VARCHAR(80)",
            "ocr_confidence": "FLOAT",
            "ocr_warnings": "JSON DEFAULT '[]'",
            "batch_id": "VARCHAR(80)",
            "pages": "JSON DEFAULT '[]'",
            "essay_prompt": "TEXT",
        },
        "grading_results": {
            "ai_engine": "VARCHAR(120)",
            "ai_metadata": "JSON DEFAULT '{}'",
        },
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
