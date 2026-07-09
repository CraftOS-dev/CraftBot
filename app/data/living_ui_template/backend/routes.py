"""
Living UI Custom Routes (agent-owned)

CRUD does NOT belong here — every entity declared in config/schema.json
already has a full generated REST API (list with filters/ordering, get,
create, update, delete, bulk) at /api/<plural>. Only add endpoints for
BEHAVIOR the generated CRUD cannot express: multi-entity transactions,
computed aggregations, external fetches, domain verbs ("archive all done
cards"), and similar.

PATH RULE (the #1 recurring mistake — read before adding routes):
  - This router is mounted with prefix="/api" in main.py.
  - Declare route paths WITHOUT /api:   @router.post("/cards/archive-done")   CORRECT
                                        @router.post("/api/cards/...")        WRONG (=> /api/api/..., 404s)
  - Your TESTS call the full path WITH /api:  client.post("/api/cards/archive-done")

Every route gets a one-line docstring (they become the generated op
descriptions for the livingui CLI). Import models by name:
`from models import Card` works for every schema entity.
"""

from fastapi import APIRouter, Depends, HTTPException  # noqa: F401
from sqlalchemy.orm import Session  # noqa: F401
from pydantic import BaseModel  # noqa: F401
from typing import Dict, Any, List, Optional  # noqa: F401
from database import get_db  # noqa: F401
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# Request bodies use Pydantic models (NEVER a bare Dict — real schemas give
# real validation errors and let the smoke tests probe your endpoint).
# Example custom endpoint (delete once you add a real one):
#
# class ClearColumnRequest(BaseModel):
#     """Body for POST /cards/clear-column."""
#     columnId: int
#
# @router.post("/cards/clear-column")
# def clear_column(req: ClearColumnRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
#     """Delete every card in a column."""
#     from models import Card
#     count = db.query(Card).filter(Card.column_id == req.columnId).delete()
#     db.commit()
#     return {"cleared": count}
