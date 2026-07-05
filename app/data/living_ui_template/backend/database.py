"""
Living UI Database Configuration

SQLite database setup for persistent state storage.
Uses synchronous SQLite with SQLAlchemy for simplicity and reliability.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Database file stored in the project directory
DATABASE_PATH = Path(__file__).parent / "living_ui.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Create engine with check_same_thread=False for FastAPI compatibility
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,  # Set to True for SQL debugging
)

# Enable WAL mode for better concurrent read/write performance (multi-user)
from sqlalchemy import event


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_added_columns():
    """Lightweight additive migration for model columns added after the DB
    already exists.

    `Base.metadata.create_all` only creates missing TABLES — it never adds a
    new column to an existing table, so a model edited after first launch
    would crash at query time. This inspects each table and issues
    `ALTER TABLE ... ADD COLUMN` for any column present in the model but
    missing on disk (additive-only; renames/drops still need manual handling).
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all handles brand-new tables
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = column.type.compile(engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                if column.default is not None and getattr(column.default, "is_scalar", False):
                    ddl += f" DEFAULT {column.default.arg!r}"
                try:
                    conn.execute(text(ddl))
                    logger.info(f"[Database] Added column {table.name}.{column.name}")
                except Exception as e:
                    logger.warning(
                        f"[Database] Could not add column {table.name}.{column.name}: {e}"
                    )


async def init_db():
    """Initialize database tables."""
    logger.info(f"[Database] Creating tables at {DATABASE_PATH}")
    Base.metadata.create_all(bind=engine)
    _migrate_added_columns()

    # Ensure default app state exists
    from models import AppState

    db = SessionLocal()
    try:
        state = db.query(AppState).first()
        if not state:
            state = AppState()
            db.add(state)
            db.commit()
            logger.info("[Database] Created default app state")
    finally:
        db.close()


def get_db():
    """
    Dependency to get database session.

    Usage in routes:
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
