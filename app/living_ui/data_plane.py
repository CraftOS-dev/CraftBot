"""
Living UI Data Plane

Direct-SQLite access layer for Living UI projects. Every native project built
from the template stores its data in ``backend/living_ui.db`` (SQLite, WAL
mode), which makes a generic, bulk-first data layer possible without any
per-project code:

- Schema introspection from the live database (ground truth — immune to a
  stale LIVING_UI.md)
- Bulk CRUD in a single transaction (100 rows = one call)
- Filtered updates/deletes so bulk data never has to pass through the model
- A guarded raw-SQL escape hatch (read-only by default)

Safety model:
- Reads open the database with ``mode=ro`` — physically unable to write.
- Writes use WAL + busy_timeout so they coexist with the running uvicorn.
- update/delete refuse to run without a ``where`` filter unless the caller
  passes ``confirm_full_table=True``.
- Every destructive call snapshots the .db file first (bounded backups).
- Table/column names are validated against the actual schema; values are
  always bound as parameters — no injection surface.

This module is the engine behind the livingui CLI's data commands.
It never runs against anything but a registered project's database.
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

# Default/maximum row counts returned by select — protects the model's
# context window from an accidental "select * from big_table".
DEFAULT_SELECT_LIMIT = 100
MAX_SELECT_LIMIT = 1000

# Keep this many pre-write snapshots per project.
MAX_DB_BACKUPS = 5

_VALID_ORDER_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(asc|desc)?\s*$", re.I)

_WHERE_OPS = {
    "=": "=",
    "==": "=",
    "eq": "=",
    "!=": "!=",
    "<>": "!=",
    "ne": "!=",
    ">": ">",
    "gt": ">",
    ">=": ">=",
    "gte": ">=",
    "<": "<",
    "lt": "<",
    "<=": "<=",
    "lte": "<=",
    "like": "LIKE",
    "not like": "NOT LIKE",
    "in": "IN",
    "not in": "NOT IN",
    "is null": "IS NULL",
    "is not null": "IS NOT NULL",
}

# Columns auto-filled on insert when the model likely has a Python-side
# default (SQLAlchemy defaults don't exist in the DB schema, so a direct
# insert would otherwise leave them NULL where the app expects a value).
_AUTO_TIMESTAMP_COLUMNS = {"created_at", "updated_at"}
_TIMESTAMP_TYPES = {"DATETIME", "TIMESTAMP", "DATE"}


class DataPlaneError(Exception):
    """A user-facing data plane failure (bad input, missing table, etc.)."""


def resolve_db_path(project: Any) -> Optional[Path]:
    """Return the project's SQLite path, or None if it doesn't have one."""
    if not project or not getattr(project, "path", None):
        return None
    db_path = Path(project.path) / "backend" / "living_ui.db"
    return db_path if db_path.exists() else None


def _connect(db_path: Path, read_only: bool) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5.0
        )
    else:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def _table_columns(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    # table has been validated against sqlite_master before this is called
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [
        {
            "name": r["name"],
            "type": r["type"] or "",
            "notNull": bool(r["notnull"]),
            "primaryKey": bool(r["pk"]),
            "default": r["dflt_value"],
        }
        for r in rows
    ]


def _require_table(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    """Validate a table exists and return its columns."""
    if not isinstance(table, str) or not table:
        raise DataPlaneError("'table' is required.")
    names = _table_names(conn)
    if table not in names:
        raise DataPlaneError(
            f"Table '{table}' not found. Available tables: {', '.join(names) or '(none)'}"
        )
    return _table_columns(conn, table)


def _require_columns(
    columns: List[str], table: str, table_columns: List[Dict[str, Any]]
) -> None:
    valid = {c["name"] for c in table_columns}
    unknown = [c for c in columns if c not in valid]
    if unknown:
        raise DataPlaneError(
            f"Unknown column(s) {unknown} on table '{table}'. "
            f"Valid columns: {sorted(valid)}"
        )


def introspect_schema(db_path: Path) -> Dict[str, Any]:
    """Return the full database schema with row counts (compact form)."""
    with _connect(db_path, read_only=True) as conn:
        tables: Dict[str, Any] = {}
        for table in _table_names(conn):
            columns = _table_columns(conn, table)
            count = conn.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"]
            tables[table] = {
                "rowCount": count,
                "columns": {
                    c["name"]: (
                        c["type"]
                        + (" PK" if c["primaryKey"] else "")
                        + (" NOT NULL" if c["notNull"] and not c["primaryKey"] else "")
                    ).strip()
                    for c in columns
                },
            }
    return tables


def compile_where(
    where: Optional[Dict[str, Any]],
    table: str,
    table_columns: List[Dict[str, Any]],
) -> Tuple[str, List[Any]]:
    """Compile a structured where object into (SQL fragment, params).

    Supported forms per column:
        {"status": "done"}                                  → status = ?
        {"priority": {"op": ">=", "value": 2}}              → priority >= ?
        {"id": {"op": "in", "value": [1, 2, 3]}}            → id IN (?,?,?)
        {"deleted_at": {"op": "is null"}}                   → deleted_at IS NULL
    Multiple keys are AND-ed. Values are always bound parameters.
    """
    if not where:
        return "", []
    if not isinstance(where, dict):
        raise DataPlaneError("'where' must be an object mapping column -> condition.")

    _require_columns(list(where.keys()), table, table_columns)

    fragments: List[str] = []
    params: List[Any] = []
    for column, condition in where.items():
        quoted = f'"{column}"'
        if isinstance(condition, dict):
            op_raw = str(condition.get("op", "=")).strip().lower()
            op = _WHERE_OPS.get(op_raw)
            if not op:
                raise DataPlaneError(
                    f"Unsupported operator '{op_raw}' for column '{column}'. "
                    f"Supported: {sorted(set(_WHERE_OPS))}"
                )
            value = condition.get("value")
            if op in ("IS NULL", "IS NOT NULL"):
                fragments.append(f"{quoted} {op}")
            elif op in ("IN", "NOT IN"):
                if not isinstance(value, list) or not value:
                    raise DataPlaneError(
                        f"Operator '{op_raw}' for column '{column}' needs a non-empty list value."
                    )
                placeholders = ", ".join("?" for _ in value)
                fragments.append(f"{quoted} {op} ({placeholders})")
                params.extend(_adapt_value(v) for v in value)
            else:
                fragments.append(f"{quoted} {op} ?")
                params.append(_adapt_value(value))
        else:
            fragments.append(f"{quoted} = ?")
            params.append(_adapt_value(condition))
    return " AND ".join(fragments), params


def _adapt_value(value: Any) -> Any:
    """Adapt a JSON-ish value for SQLite binding (dicts/lists become JSON)."""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def backup_db(db_path: Path) -> Optional[Path]:
    """Snapshot the database before a destructive operation (bounded)."""
    try:
        backup_dir = db_path.parent / "logs" / "db_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = backup_dir / f"living_ui_{stamp}.db"
        # sqlite3 backup API is consistent even mid-write (unlike file copy)
        with _connect(db_path, read_only=True) as src:
            dest = sqlite3.connect(str(backup_path))
            try:
                src.backup(dest)
            finally:
                dest.close()
        # Prune old snapshots
        snapshots = sorted(backup_dir.glob("living_ui_*.db"), reverse=True)
        for old in snapshots[MAX_DB_BACKUPS:]:
            try:
                old.unlink()
            except Exception:
                pass
        return backup_path
    except Exception as e:
        logger.warning(f"[LIVING_UI:DATA] Backup failed for {db_path}: {e}")
        return None


def _compile_order_by(
    order_by: Any, table: str, table_columns: List[Dict[str, Any]]
) -> str:
    if not order_by:
        return ""
    if isinstance(order_by, str):
        order_by = [order_by]
    if not isinstance(order_by, list):
        raise DataPlaneError("'order_by' must be a string or list of strings.")
    parts = []
    for entry in order_by:
        m = _VALID_ORDER_RE.match(str(entry))
        if not m:
            raise DataPlaneError(
                f"Invalid order_by entry '{entry}'. Use 'column' or 'column desc'."
            )
        column, direction = m.group(1), (m.group(2) or "asc").upper()
        _require_columns([column], table, table_columns)
        parts.append(f'"{column}" {direction}')
    return " ORDER BY " + ", ".join(parts)


def select_rows(
    db_path: Path,
    table: str,
    where: Optional[Dict[str, Any]] = None,
    columns: Optional[List[str]] = None,
    order_by: Any = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> Dict[str, Any]:
    with _connect(db_path, read_only=True) as conn:
        table_columns = _require_table(conn, table)
        if columns:
            _require_columns(columns, table, table_columns)
            select_list = ", ".join(f'"{c}"' for c in columns)
        else:
            select_list = "*"
        where_sql, params = compile_where(where, table, table_columns)
        order_sql = _compile_order_by(order_by, table, table_columns)

        effective_limit = DEFAULT_SELECT_LIMIT if limit is None else int(limit)
        truncated_note = None
        if effective_limit > MAX_SELECT_LIMIT:
            truncated_note = f"limit clamped to {MAX_SELECT_LIMIT}"
            effective_limit = MAX_SELECT_LIMIT

        sql = f'SELECT {select_list} FROM "{table}"'
        if where_sql:
            sql += f" WHERE {where_sql}"
        sql += order_sql
        sql += " LIMIT ? OFFSET ?"
        rows = conn.execute(sql, params + [effective_limit, int(offset)]).fetchall()

        # Total matching count so the agent knows if it saw everything
        count_sql = f'SELECT COUNT(*) AS n FROM "{table}"'
        if where_sql:
            count_sql += f" WHERE {where_sql}"
        total = conn.execute(count_sql, params).fetchone()["n"]

    result = {
        "rows": [_row_to_dict(r) for r in rows],
        "returned": len(rows),
        "total_matching": total,
    }
    if truncated_note:
        result["note"] = truncated_note
    return result


def count_rows(
    db_path: Path, table: str, where: Optional[Dict[str, Any]] = None
) -> int:
    with _connect(db_path, read_only=True) as conn:
        table_columns = _require_table(conn, table)
        where_sql, params = compile_where(where, table, table_columns)
        sql = f'SELECT COUNT(*) AS n FROM "{table}"'
        if where_sql:
            sql += f" WHERE {where_sql}"
        return conn.execute(sql, params).fetchone()["n"]


def _prepare_insert_rows(
    rows: List[Dict[str, Any]], table: str, table_columns: List[Dict[str, Any]]
) -> Tuple[List[str], List[List[Any]], List[str]]:
    """Validate + adapt rows; auto-fill Python-side timestamp defaults."""
    if not isinstance(rows, list) or not rows:
        raise DataPlaneError("'rows' must be a non-empty list of objects.")
    if not all(isinstance(r, dict) and r for r in rows):
        raise DataPlaneError("Every entry in 'rows' must be a non-empty object.")

    all_keys: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in all_keys:
                all_keys.append(k)
    _require_columns(all_keys, table, table_columns)

    # Auto-fill created_at/updated_at style columns the rows don't provide —
    # SQLAlchemy-level defaults don't exist in the DB schema.
    autofilled: List[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    for col in table_columns:
        name = col["name"]
        if (
            name in _AUTO_TIMESTAMP_COLUMNS
            and name not in all_keys
            and col["default"] is None
            and not col["primaryKey"]
            and any(t in (col["type"] or "").upper() for t in _TIMESTAMP_TYPES)
        ):
            all_keys.append(name)
            autofilled.append(name)

    values: List[List[Any]] = []
    for r in rows:
        row_values = []
        for k in all_keys:
            if k in autofilled:
                row_values.append(now)
            else:
                row_values.append(_adapt_value(r.get(k)))
        values.append(row_values)
    return all_keys, values, autofilled


def insert_rows(db_path: Path, table: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    with _connect(db_path, read_only=False) as conn:
        table_columns = _require_table(conn, table)
        keys, values, autofilled = _prepare_insert_rows(rows, table, table_columns)
        column_list = ", ".join(f'"{k}"' for k in keys)
        placeholders = ", ".join("?" for _ in keys)
        sql = f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders})'
        with conn:  # single transaction — all rows or none
            cursor = conn.executemany(sql, values)
            inserted = cursor.rowcount
            last_id = conn.execute("SELECT last_insert_rowid() AS n").fetchone()["n"]
    result: Dict[str, Any] = {"inserted": inserted, "last_row_id": last_id}
    if autofilled:
        result["autofilled_columns"] = autofilled
    return result


def update_rows(
    db_path: Path,
    table: str,
    values: Dict[str, Any],
    where: Optional[Dict[str, Any]] = None,
    confirm_full_table: bool = False,
) -> Dict[str, Any]:
    if not isinstance(values, dict) or not values:
        raise DataPlaneError("'values' must be a non-empty object of column -> new value.")
    if not where and not confirm_full_table:
        raise DataPlaneError(
            "Refusing to update every row: pass a 'where' filter, or set "
            "confirm_full_table=true if you really mean the whole table."
        )
    backup_path = backup_db(db_path)
    with _connect(db_path, read_only=False) as conn:
        table_columns = _require_table(conn, table)
        _require_columns(list(values.keys()), table, table_columns)
        where_sql, where_params = compile_where(where, table, table_columns)
        set_sql = ", ".join(f'"{k}" = ?' for k in values.keys())
        set_params = [_adapt_value(v) for v in values.values()]
        sql = f'UPDATE "{table}" SET {set_sql}'
        if where_sql:
            sql += f" WHERE {where_sql}"
        with conn:
            cursor = conn.execute(sql, set_params + where_params)
            updated = cursor.rowcount
    return {
        "updated": updated,
        "backup": str(backup_path) if backup_path else None,
    }


def delete_rows(
    db_path: Path,
    table: str,
    where: Optional[Dict[str, Any]] = None,
    confirm_full_table: bool = False,
) -> Dict[str, Any]:
    if not where and not confirm_full_table:
        raise DataPlaneError(
            "Refusing to delete every row: pass a 'where' filter, or set "
            "confirm_full_table=true if you really mean the whole table."
        )
    backup_path = backup_db(db_path)
    with _connect(db_path, read_only=False) as conn:
        table_columns = _require_table(conn, table)
        where_sql, params = compile_where(where, table, table_columns)
        sql = f'DELETE FROM "{table}"'
        if where_sql:
            sql += f" WHERE {where_sql}"
        with conn:
            cursor = conn.execute(sql, params)
            deleted = cursor.rowcount
    return {
        "deleted": deleted,
        "backup": str(backup_path) if backup_path else None,
    }


def upsert_rows(
    db_path: Path, table: str, rows: List[Dict[str, Any]], key_columns: List[str]
) -> Dict[str, Any]:
    if not isinstance(key_columns, list) or not key_columns:
        raise DataPlaneError("'key_columns' must be a non-empty list.")
    backup_path = backup_db(db_path)
    with _connect(db_path, read_only=False) as conn:
        table_columns = _require_table(conn, table)
        _require_columns(key_columns, table, table_columns)
        keys, values, autofilled = _prepare_insert_rows(rows, table, table_columns)
        missing_keys = [k for k in key_columns if k not in keys]
        if missing_keys:
            raise DataPlaneError(
                f"Every row must include the key column(s) {missing_keys} for upsert."
            )
        column_list = ", ".join(f'"{k}"' for k in keys)
        placeholders = ", ".join("?" for _ in keys)
        conflict_cols = ", ".join(f'"{k}"' for k in key_columns)
        update_cols = [k for k in keys if k not in key_columns]
        if update_cols:
            update_sql = ", ".join(f'"{k}" = excluded."{k}"' for k in update_cols)
            sql = (
                f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders}) '
                f"ON CONFLICT({conflict_cols}) DO UPDATE SET {update_sql}"
            )
        else:
            sql = (
                f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders}) '
                f"ON CONFLICT({conflict_cols}) DO NOTHING"
            )
        try:
            with conn:
                cursor = conn.executemany(sql, values)
                affected = cursor.rowcount
        except sqlite3.OperationalError as e:
            if "ON CONFLICT" in str(e):
                raise DataPlaneError(
                    f"Upsert needs a UNIQUE constraint/index on ({conflict_cols}) "
                    f"— none exists on '{table}'. Original error: {e}"
                )
            raise
    result: Dict[str, Any] = {
        "affected": affected,
        "backup": str(backup_path) if backup_path else None,
    }
    if autofilled:
        result["autofilled_columns"] = autofilled
    return result


def run_sql(
    db_path: Path,
    sql: str,
    params: Optional[Any] = None,
    write: bool = False,
) -> Dict[str, Any]:
    """Run raw SQL. Read mode uses a read-only connection (cannot write).

    Write mode enforces a single statement and snapshots the DB first.
    Params may be a list (positional ?) or dict (named :param).
    """
    if not isinstance(sql, str) or not sql.strip():
        raise DataPlaneError("'sql' is required.")
    sql = sql.strip()
    bind = params if params is not None else []

    if not write:
        with _connect(db_path, read_only=True) as conn:
            try:
                cursor = conn.execute(sql, bind)
            except sqlite3.OperationalError as e:
                if "readonly" in str(e).lower() or "read-only" in str(e).lower():
                    raise DataPlaneError(
                        "This statement writes data. Re-run with mode='write' "
                        "(a backup will be taken first)."
                    )
                raise DataPlaneError(f"SQL error: {e}")
            rows = cursor.fetchmany(MAX_SELECT_LIMIT + 1)
            truncated = len(rows) > MAX_SELECT_LIMIT
            rows = rows[:MAX_SELECT_LIMIT]
            result: Dict[str, Any] = {
                "rows": [_row_to_dict(r) for r in rows],
                "returned": len(rows),
            }
            if truncated:
                result["note"] = f"result truncated to {MAX_SELECT_LIMIT} rows"
            return result

    # Write mode: single statement only, backup first
    body = sql.rstrip().rstrip(";")
    if ";" in body:
        raise DataPlaneError(
            "Write mode accepts a single SQL statement (no ';' separators)."
        )
    backup_path = backup_db(db_path)
    with _connect(db_path, read_only=False) as conn:
        try:
            with conn:
                cursor = conn.execute(sql, bind)
                affected = cursor.rowcount
        except sqlite3.Error as e:
            raise DataPlaneError(f"SQL error: {e}")
    return {
        "affected": affected,
        "backup": str(backup_path) if backup_path else None,
    }
