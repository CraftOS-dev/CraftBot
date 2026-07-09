"""
Living UI Data Engine (SYSTEM-MANAGED — do not edit)

The backend is CONFIGURED, not hand-written: the agent declares the app's
entities in config/schema.json and this engine materializes, at import time,

  - one SQLAlchemy model per entity (proper autoincrement integer `id`,
    `created_at`/`updated_at` timestamps, camelCase `to_dict()`), and
  - a full REST surface per entity:

        GET    /api/<plural>            list (equality filters on any field,
                                        ?q= search over string/text/enum,
                                        range filters <field>_gte/_lte/_gt/_lt,
                                        plus orderBy, order, limit, offset)
        GET    /api/<plural>/_stats     count/sum/avg, optionally grouped
        POST   /api/<plural>            create (validates required fields)
        POST   /api/<plural>/bulk       create many in one transaction
        GET    /api/<plural>/{id}       fetch one (404 when missing)
        PUT    /api/<plural>/{id}       partial update
        DELETE /api/<plural>/{id}       delete (+ relationship handling)
        GET    /api/_meta/schema        the parsed schema + generated routes

Field values are camelCase on the wire (matching the frontend) and
snake_case in the database; the engine converts. `datetime` fields accept
and emit ISO-8601 strings. `ref` fields hold the integer id of the target
entity; deleting a parent CASCADES to children whose ref is required and
NULLS children whose ref is optional (override per-field with "onDelete").

A broken schema.json fails LOUDLY at import with a message naming the
entity/field — the internal validation test surfaces it verbatim.
"""

import json
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Type

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import create_model
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, JSON, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from system_models import Base

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent.parent / "config" / "schema.json"

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")

_TYPE_FACTORIES = {
    "string": lambda: String(255),
    "text": lambda: Text,
    "integer": lambda: Integer,
    "float": lambda: Float,
    "boolean": lambda: Boolean,
    "datetime": lambda: DateTime,
    "json": lambda: JSON,
    "ref": lambda: Integer,
    "enum": lambda: String(64),  # values validated by the request model
}

# Field names the engine provides on every entity; schemas must not redefine.
_RESERVED_FIELDS = {"id", "createdAt", "updatedAt"}


class SchemaError(ValueError):
    """Invalid config/schema.json — message names the exact problem."""


def _snake(name: str) -> str:
    """camelCase / PascalCase -> snake_case."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def _plural(name: str) -> str:
    """Naive English pluralization for route paths (override with "plural")."""
    lower = _snake(name)
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return lower + "es"
    if lower.endswith("y") and lower[-2] not in "aeiou":
        return lower[:-1] + "ies"
    return lower + "s"


def load_schema() -> Dict[str, Any]:
    """Read config/schema.json. Missing file / no entities => empty app."""
    if not SCHEMA_PATH.exists():
        return {"entities": {}}
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SchemaError(f"config/schema.json is not valid JSON: {e}") from e
    if not isinstance(schema.get("entities", {}), dict):
        raise SchemaError('config/schema.json: "entities" must be an object')
    return schema


def _validate_field(entity: str, field: str, spec: Dict[str, Any], entities: set):
    if field in _RESERVED_FIELDS:
        raise SchemaError(
            f"{entity}.{field}: '{field}' is provided automatically by the "
            f"engine — remove it from the schema"
        )
    if not _NAME_RE.match(field):
        raise SchemaError(
            f"{entity}.{field}: field names must be alphanumeric camelCase"
        )
    if not isinstance(spec, dict):
        raise SchemaError(
            f'{entity}.{field}: field spec must be an object like '
            f'{{"type": "string"}}'
        )
    ftype = spec.get("type")
    if ftype not in _TYPE_FACTORIES:
        raise SchemaError(
            f"{entity}.{field}: unknown type {ftype!r} — one of "
            f"{sorted(_TYPE_FACTORIES)}"
        )
    if ftype == "ref":
        target = spec.get("entity")
        if target not in entities:
            raise SchemaError(
                f'{entity}.{field}: ref must name an entity in this schema '
                f'("entity": {target!r} not found)'
            )
    if ftype == "enum":
        values = spec.get("values")
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(v, str) and v for v in values)
        ):
            raise SchemaError(
                f'{entity}.{field}: enum needs "values": ["a", "b", ...] '
                f"(non-empty list of strings)"
            )
    if spec.get("unique") and ftype in ("json", "boolean"):
        raise SchemaError(
            f"{entity}.{field}: unique is not supported on {ftype} fields"
        )


def build_models(schema: Dict[str, Any]) -> Dict[str, Type]:
    """Materialize one SQLAlchemy model per schema entity onto Base."""
    entities = schema.get("entities", {})
    names = set(entities)
    models: Dict[str, Type] = {}

    for entity_name, entity_spec in entities.items():
        if not _NAME_RE.match(entity_name):
            raise SchemaError(
                f"Entity {entity_name!r}: names must be alphanumeric PascalCase"
            )
        fields = entity_spec.get("fields", {})
        if not isinstance(fields, dict):
            raise SchemaError(f'{entity_name}: "fields" must be an object')

        attrs: Dict[str, Any] = {
            "__tablename__": _snake(entity_name),
            "id": Column(Integer, primary_key=True, autoincrement=True),
            "created_at": Column(DateTime, default=datetime.utcnow),
            "updated_at": Column(
                DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
            ),
        }
        field_meta: Dict[str, Dict[str, Any]] = {}

        for field_name, spec in fields.items():
            _validate_field(entity_name, field_name, spec, names)
            col_name = _snake(field_name)
            required = bool(spec.get("required", False))
            default = spec.get("default")
            col_type = _TYPE_FACTORIES[spec["type"]]()
            kwargs: Dict[str, Any] = {"nullable": not required}
            if spec.get("unique"):
                kwargs["unique"] = True
            if default is not None:
                kwargs["default"] = default
            elif spec["type"] == "json":
                kwargs["default"] = dict
            attrs[col_name] = Column(col_type, **kwargs)
            field_meta[field_name] = {
                "column": col_name,
                "type": spec["type"],
                "required": required,
                "unique": bool(spec.get("unique")),
                "values": spec.get("values"),
                "entity": spec.get("entity"),
                # required ref -> cascade (child can't exist without parent);
                # optional ref -> null out. Overridable per field.
                "onDelete": spec.get(
                    "onDelete", "cascade" if required and spec["type"] == "ref" else "null"
                ),
            }

        def _make_to_dict(meta: Dict[str, Dict[str, Any]]):
            def to_dict(self) -> Dict[str, Any]:
                out: Dict[str, Any] = {"id": self.id}
                for fname, m in meta.items():
                    value = getattr(self, m["column"])
                    if m["type"] == "datetime" and value is not None:
                        value = value.isoformat()
                    out[fname] = value
                out["createdAt"] = (
                    self.created_at.isoformat() if self.created_at else None
                )
                out["updatedAt"] = (
                    self.updated_at.isoformat() if self.updated_at else None
                )
                return out

            return to_dict

        attrs["to_dict"] = _make_to_dict(field_meta)
        attrs["__engine_fields__"] = field_meta
        attrs["__engine_plural__"] = str(
            entity_spec.get("plural") or _plural(entity_name)
        )
        attrs["__doc__"] = entity_spec.get("description", f"{entity_name} entity")

        models[entity_name] = type(entity_name, (Base,), attrs)
        logger.info(
            f"[Engine] Materialized {entity_name} "
            f"({len(field_meta)} fields, /{attrs['__engine_plural__']})"
        )

    return models


# ── module-level singleton: schema + models build once at import ────────────

SCHEMA: Dict[str, Any] = load_schema()
MODELS: Dict[str, Type] = build_models(SCHEMA)


def get_models() -> Dict[str, Type]:
    return MODELS


# ── value coercion (wire -> column) ─────────────────────────────────────────


def _coerce(entity: str, fname: str, meta: Dict[str, Any], value: Any) -> Any:
    if value is None:
        return None
    ftype = meta["type"]
    try:
        if ftype == "datetime" and isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        if ftype == "integer" and not isinstance(value, bool):
            return int(value)
        if ftype == "float":
            return float(value)
        if ftype == "boolean":
            if isinstance(value, str):
                return value.lower() in ("1", "true", "yes")
            return bool(value)
        if ftype == "ref":
            return int(value)
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=422,
            detail=f"{entity}.{fname}: cannot interpret {value!r} as {ftype} ({e})",
        )
    return value


def _commit_translating_unique(db: Session, entity: str, meta: Dict[str, Dict[str, Any]]):
    """Commit; translate a UNIQUE violation into a 409 naming the field."""
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        text = str(e.orig or e)
        field = next(
            (
                fname
                for fname, m in meta.items()
                if m.get("unique") and m["column"] in text
            ),
            None,
        )
        detail = (
            f"{entity}.{field}: value already exists (unique)"
            if field
            else f"{entity}: unique constraint violated ({text.splitlines()[-1][:200]})"
        )
        raise HTTPException(status_code=409, detail=detail)


def _payload_to_columns(
    entity: str, model: Type, payload: Dict[str, Any], require_required: bool
) -> Dict[str, Any]:
    """Map a camelCase wire payload onto column kwargs, validating types and
    (on create) required fields. Unknown keys are ignored."""
    meta: Dict[str, Dict[str, Any]] = model.__engine_fields__
    out: Dict[str, Any] = {}
    for fname, m in meta.items():
        if fname in payload:
            out[m["column"]] = _coerce(entity, fname, m, payload[fname])
    if require_required:
        missing = [
            fname
            for fname, m in meta.items()
            if m["required"] and payload.get(fname) is None
        ]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"{entity}: missing required field(s): {', '.join(missing)}",
            )
    return out


# ── relationship handling on delete ──────────────────────────────────────────


def _children_of(entity_name: str) -> List[Tuple[Type, str, str]]:
    """[(child_model, ref_column, onDelete)] for refs pointing at entity."""
    out = []
    for child in MODELS.values():
        for m in child.__engine_fields__.values():
            if m["type"] == "ref" and m["entity"] == entity_name:
                out.append((child, m["column"], m["onDelete"]))
    return out


def _delete_with_relations(db: Session, entity_name: str, obj: Any) -> int:
    """Delete obj; cascade/null children per their onDelete. Returns count."""
    deleted = 1
    for child_model, ref_col, on_delete in _children_of(entity_name):
        children = (
            db.query(child_model).filter(getattr(child_model, ref_col) == obj.id).all()
        )
        for child in children:
            if on_delete == "cascade":
                deleted += _delete_with_relations(db, child_model.__name__, child)
            else:
                setattr(child, ref_col, None)
    db.delete(obj)
    return deleted


# ── request models (real OpenAPI schemas per entity) ────────────────────────

_PY_TYPES = {
    "enum": str,  # replaced by Literal[values] in _request_models
    "string": str,
    "text": str,
    "integer": int,
    "float": float,
    "boolean": bool,
    "datetime": datetime,
    "json": Any,
    "ref": int,
}


def _request_models(entity_name: str, meta: Dict[str, Dict[str, Any]]):
    """Pydantic create/update models: create requires the schema's required
    fields; update is fully partial. Real properties in OpenAPI means real
    validation errors AND probe-able smoke tests."""
    create_fields: Dict[str, Any] = {}
    update_fields: Dict[str, Any] = {}
    for fname, m in meta.items():
        if m["type"] == "enum":
            py = Literal[tuple(m["values"])]
        else:
            py = _PY_TYPES[m["type"]]
        if m["required"]:
            create_fields[fname] = (py, ...)
        else:
            create_fields[fname] = (Optional[py], None)
        update_fields[fname] = (Optional[py], None)
    return (
        create_model(f"{entity_name}Create", **create_fields),
        create_model(f"{entity_name}Update", **update_fields),
    )


def _model_data(payload) -> Dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    return payload.dict(exclude_unset=True)


# ── CRUD router ──────────────────────────────────────────────────────────────

_LIST_CONTROLS = {"orderBy", "order", "limit", "offset"}


def build_router() -> APIRouter:
    from database import get_db  # deferred: database imports models

    from fastapi import Depends

    router = APIRouter()

    @router.get("/_meta/schema")
    def get_schema_meta() -> Dict[str, Any]:
        """The app's data schema and the REST surface generated from it."""
        return {
            "entities": SCHEMA.get("entities", {}),
            "routes": {
                name: f"/api/{model.__engine_plural__}"
                for name, model in MODELS.items()
            },
        }

    for entity_name, model in MODELS.items():
        _register_crud(router, entity_name, model, get_db)

    return router


def _register_crud(router: APIRouter, entity_name: str, model: Type, get_db):
    from fastapi import Depends

    plural = model.__engine_plural__
    meta: Dict[str, Dict[str, Any]] = model.__engine_fields__
    create_cls, update_cls = _request_models(entity_name, meta)

    def _get_or_404(db: Session, item_id: int):
        obj = db.query(model).filter(model.id == item_id).first()
        if not obj:
            raise HTTPException(
                status_code=404, detail=f"{entity_name} {item_id} not found"
            )
        return obj

    @router.get(f"/{plural}", name=f"list_{plural}")
    def list_items(
        request: Request, db: Session = Depends(get_db)
    ) -> List[Dict[str, Any]]:
        query = db.query(model)
        params = dict(request.query_params)
        order_by = params.pop("orderBy", None)
        order = params.pop("order", "asc")
        limit = params.pop("limit", None)
        offset = params.pop("offset", None)
        q = params.pop("q", None)
        if q:
            # Case-insensitive substring search across text-ish fields.
            text_cols = [
                getattr(model, m["column"])
                for m in meta.values()
                if m["type"] in ("string", "text", "enum")
            ]
            if text_cols:
                from sqlalchemy import or_

                like = f"%{q}%"
                query = query.filter(or_(*(c.ilike(like) for c in text_cols)))
        for key, raw in params.items():
            # Range filters: <field>_gte / _lte / _gt / _lt on
            # integer/float/datetime fields.
            base, op = key, None
            for suffix in ("_gte", "_lte", "_gt", "_lt"):
                if key.endswith(suffix):
                    base, op = key[: -len(suffix)], suffix[1:]
                    break
            m = meta.get(base)
            if not m or (op and m["type"] not in ("integer", "float", "datetime", "ref")):
                raise HTTPException(
                    status_code=422,
                    detail=f"{entity_name}: unknown filter field {key!r}",
                )
            col = getattr(model, m["column"])
            value = _coerce(entity_name, base, m, raw)
            if op == "gte":
                query = query.filter(col >= value)
            elif op == "lte":
                query = query.filter(col <= value)
            elif op == "gt":
                query = query.filter(col > value)
            elif op == "lt":
                query = query.filter(col < value)
            else:
                query = query.filter(col == value)
        if order_by:
            m = meta.get(order_by)
            col = getattr(model, m["column"]) if m else (
                model.created_at if order_by == "createdAt" else None
            )
            if col is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{entity_name}: unknown orderBy field {order_by!r}",
                )
            query = query.order_by(col.desc() if order == "desc" else col.asc())
        if offset:
            query = query.offset(int(offset))
        if limit:
            query = query.limit(int(limit))
        return [obj.to_dict() for obj in query.all()]

    @router.get(f"/{plural}/_stats", name=f"stats_{plural}")
    def stats(
        groupBy: Optional[str] = None,
        agg: str = "count",
        field: Optional[str] = None,
        db: Session = Depends(get_db),
    ) -> Any:
        """Declared aggregations: count/sum/avg, optionally grouped."""
        if agg not in ("count", "sum", "avg"):
            raise HTTPException(status_code=422, detail=f"unknown agg {agg!r}")
        if agg in ("sum", "avg"):
            fm = meta.get(field or "")
            if not fm or fm["type"] not in ("integer", "float"):
                raise HTTPException(
                    status_code=422,
                    detail=f"{agg} needs field=<integer|float schema field>",
                )
            agg_col = getattr(model, fm["column"])
            agg_expr = func.sum(agg_col) if agg == "sum" else func.avg(agg_col)
        else:
            agg_expr = func.count(model.id)
        if not groupBy:
            value = db.query(agg_expr).scalar()
            return {"value": value if value is not None else 0}
        gm = meta.get(groupBy)
        if not gm:
            raise HTTPException(
                status_code=422,
                detail=f"{entity_name}: unknown groupBy field {groupBy!r}",
            )
        group_col = getattr(model, gm["column"])
        rows = db.query(group_col, agg_expr).group_by(group_col).all()
        return [{"group": g, "value": v} for g, v in rows]

    @router.post(f"/{plural}", name=f"create_{plural}")
    def create_item(
        payload: create_cls, db: Session = Depends(get_db)
    ) -> Dict[str, Any]:
        data = _model_data(payload)
        obj = model(**_payload_to_columns(entity_name, model, data, True))
        db.add(obj)
        _commit_translating_unique(db, entity_name, meta)
        db.refresh(obj)
        return obj.to_dict()

    @router.post(f"/{plural}/bulk", name=f"bulk_create_{plural}")
    def bulk_create(
        payload: Optional[List[create_cls]] = Body(None),
        db: Session = Depends(get_db),
    ) -> List[Dict[str, Any]]:
        if not payload:
            return []  # no body / empty array = create nothing (probe-safe)
        objs = [
            model(**_payload_to_columns(entity_name, model, _model_data(row), True))
            for row in payload
        ]
        db.add_all(objs)
        _commit_translating_unique(db, entity_name, meta)
        for obj in objs:
            db.refresh(obj)
        return [obj.to_dict() for obj in objs]

    @router.get(f"/{plural}/{{item_id}}", name=f"get_{plural}")
    def get_item(item_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
        return _get_or_404(db, item_id).to_dict()

    @router.put(f"/{plural}/{{item_id}}", name=f"update_{plural}")
    def update_item(
        item_id: int,
        payload: update_cls,
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        obj = _get_or_404(db, item_id)
        for col, value in _payload_to_columns(
            entity_name, model, _model_data(payload), False
        ).items():
            setattr(obj, col, value)
        obj.updated_at = datetime.utcnow()
        _commit_translating_unique(db, entity_name, meta)
        db.refresh(obj)
        return obj.to_dict()

    @router.delete(f"/{plural}/{{item_id}}", name=f"delete_{plural}")
    def delete_item(item_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
        # Idempotent: deleting an id that's already gone (e.g. removed by a
        # parent's cascade) succeeds with deleted=0 instead of 404.
        obj = db.query(model).filter(model.id == item_id).first()
        if not obj:
            return {"status": "deleted", "deleted": 0}
        deleted = _delete_with_relations(db, entity_name, obj)
        db.commit()
        return {"status": "deleted", "deleted": deleted}
