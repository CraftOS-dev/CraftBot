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


async def init_db():
    """Initialize database tables."""
    logger.info(f"[Database] Creating tables at {DATABASE_PATH}")
    Base.metadata.create_all(bind=engine)

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
