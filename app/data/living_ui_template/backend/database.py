"""
Living UI Database Configuration

Defaults to a local SQLite file. To point the app at an EXTERNAL database
(Supabase, any Postgres), write `backend/.env` with a single line:

    DATABASE_URL=postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres

Everything else — the schema engine's generated models/CRUD, the reconcile
migration, the livingui CLI's data commands — follows this setting
automatically. NEVER hardcode a connection string in code, and never log
or print it (it contains the database password).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Default database file stored in the project directory
DATABASE_PATH = Path(__file__).parent / "living_ui.db"


def _load_database_url() -> str:
    """DATABASE_URL from backend/.env, else the local SQLite file.

    The .env file (KEY=VALUE lines, # comments) is the ONLY source — the
    process environment is deliberately ignored so a machine-wide
    DATABASE_URL can never silently repoint every Living UI.
    """
    env_file = Path(__file__).parent / ".env"
    try:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == "DATABASE_URL":
                    url = value.strip().strip("'\"")
                    if url and not url.startswith("sqlite"):
                        return url
    except OSError:
        pass
    return f"sqlite:///{DATABASE_PATH}"


DATABASE_URL = _load_database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    # check_same_thread=False for FastAPI compatibility
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,  # Set to True for SQL debugging
    )
else:
    # External database (Supabase/Postgres): verify connections before use
    # so a dropped pooled connection surfaces as a retry, not a 500.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)
    logger.info("[Database] Using external database (DATABASE_URL from .env)")

# Enable WAL mode for better concurrent read/write performance (SQLite only)
from sqlalchemy import event

if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_added_columns():
    """Schema reconcile migration, run at every startup.

    `Base.metadata.create_all` only creates missing TABLES. Two drift cases
    are handled here so a schema.json edit after first launch never turns
    into runtime 500s:
      - column in the model but missing on disk -> ALTER TABLE ADD COLUMN
      - column on disk but no longer in the model (field removed/renamed)
        -> rebuild the table from the model, copying shared columns' data
        (a stale NOT NULL column would otherwise fail every INSERT).
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all handles brand-new tables
            disk_cols = {c["name"] for c in inspector.get_columns(table.name)}
            model_cols = [c.name for c in table.columns]
            stale = sorted(disk_cols - set(model_cols))

            if stale:
                shared = [c for c in model_cols if c in disk_cols]
                tmp = f"{table.name}__craftbot_stale"
                try:
                    conn.execute(text(f'ALTER TABLE "{table.name}" RENAME TO "{tmp}"'))
                    table.create(bind=conn)
                    if shared:
                        # New columns get their scalar defaults explicitly:
                        # model defaults are Python-side (no DDL DEFAULT), so
                        # a plain INSERT..SELECT would NULL-violate new
                        # required columns (e.g. a renamed enum field).
                        fill_cols, fill_params = [], {}
                        for column in table.columns:
                            if column.name in shared:
                                continue
                            default = column.default
                            if default is not None and getattr(default, "is_scalar", False):
                                if isinstance(default.arg, (str, int, float, bool)):
                                    fill_cols.append(column.name)
                                    fill_params[f"d_{column.name}"] = default.arg
                        cols_sql = ", ".join(
                            f'"{c}"' for c in shared + fill_cols
                        )
                        select_sql = ", ".join(
                            [f'"{c}"' for c in shared]
                            + [f":d_{c}" for c in fill_cols]
                        )
                        try:
                            conn.execute(
                                text(
                                    f'INSERT INTO "{table.name}" ({cols_sql}) '
                                    f'SELECT {select_sql} FROM "{tmp}"'
                                ),
                                fill_params,
                            )
                        except Exception as e:
                            logger.warning(
                                f"[Database] {table.name} rebuilt but rows not "
                                f"copied ({e}) — table starts empty"
                            )
                    conn.execute(text(f'DROP TABLE "{tmp}"'))
                    logger.info(
                        f"[Database] Rebuilt {table.name} "
                        f"(removed stale columns: {', '.join(stale)})"
                    )
                except Exception as e:
                    logger.warning(f"[Database] Could not rebuild {table.name}: {e}")
                continue

            for column in table.columns:
                if column.name in disk_cols:
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
    logger.info(
        "[Database] Creating tables at "
        + (str(DATABASE_PATH) if IS_SQLITE else "external database")
    )
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
