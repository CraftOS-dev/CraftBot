"""
Living UI API Routes

REST API endpoints for state management and data operations.
Provides both generic state storage and example CRUD operations.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from database import get_db
from models import AppState, Item, UISnapshot, UIScreenshot
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# Pydantic Schemas
# ============================================================================


class StateUpdate(BaseModel):
    """Schema for updating app state."""

    data: Dict[str, Any]


class ActionRequest(BaseModel):
    """Schema for executing an action."""

    action: str
    payload: Optional[Dict[str, Any]] = None


class ItemCreate(BaseModel):
    """Schema for creating an item."""

    title: str
    description: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


class ItemUpdate(BaseModel):
    """Schema for updating an item."""

    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None
    order: Optional[int] = None
    extra_data: Optional[Dict[str, Any]] = None


class UISnapshotUpdate(BaseModel):
    """Schema for updating UI snapshot."""

    htmlStructure: Optional[str] = None
    visibleText: Optional[List[str]] = None
    inputValues: Optional[Dict[str, Any]] = None
    componentState: Optional[Dict[str, Any]] = None
    currentView: Optional[str] = None
    viewport: Optional[Dict[str, Any]] = None


class UIScreenshotUpdate(BaseModel):
    """Schema for updating UI screenshot."""

    imageData: str  # Base64 encoded PNG
    width: Optional[int] = None
    height: Optional[int] = None


# ============================================================================
# State Management Routes (Primary API)
# ============================================================================


@router.get("/state")
def get_state(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get the current application state.

    Returns the stored state data, or empty dict if no state exists.
    Frontend calls this on mount to restore state.
    """
    state = db.query(AppState).first()
    if not state:
        state = AppState(data={})
        db.add(state)
        db.commit()
        db.refresh(state)
    return state.data or {}


@router.put("/state")
def update_state(update: StateUpdate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Update the application state.

    Merges the provided data with existing state.
    Returns the complete updated state.
    """
    state = db.query(AppState).first()
    if not state:
        state = AppState(data=update.data)
        db.add(state)
    else:
        state.update_data(update.data)
    db.commit()
    db.refresh(state)
    logger.info(f"[Routes] State updated: {list(update.data.keys())}")
    return state.data or {}


@router.post("/state/replace")
def replace_state(update: StateUpdate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Replace the entire application state.

    Unlike PUT /state which merges, this completely replaces the state.
    Use with caution.
    """
    state = db.query(AppState).first()
    if not state:
        state = AppState(data=update.data)
        db.add(state)
    else:
        state.data = update.data
    db.commit()
    db.refresh(state)
    logger.info("[Routes] State replaced")
    return state.data or {}


@router.delete("/state")
def clear_state(db: Session = Depends(get_db)) -> Dict[str, str]:
    """
    Clear all application state.

    Resets state to empty dict.
    """
    state = db.query(AppState).first()
    if state:
        state.data = {}
        db.commit()
    logger.info("[Routes] State cleared")
    return {"status": "cleared"}


@router.post("/action")
def execute_action(
    request: ActionRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Execute a named action.

    This is a generic endpoint for custom actions.
    The agent should customize this based on the Living UI's needs.

    Example actions:
    - {"action": "reset"} - Reset to initial state
    - {"action": "increment", "payload": {"key": "counter"}}
    """
    action = request.action
    payload = request.payload or {}

    logger.info(f"[Routes] Executing action: {action}")

    # Get current state
    state = db.query(AppState).first()
    if not state:
        state = AppState(data={})
        db.add(state)

    current_data = state.data or {}

    # Handle built-in actions
    if action == "reset":
        state.data = {}
        db.commit()
        return {"status": "reset", "data": {}}

    elif action == "increment":
        key = payload.get("key", "counter")
        current_data[key] = current_data.get(key, 0) + 1
        state.data = current_data
        db.commit()
        return {"status": "incremented", "data": current_data}

    elif action == "decrement":
        key = payload.get("key", "counter")
        current_data[key] = current_data.get(key, 0) - 1
        state.data = current_data
        db.commit()
        return {"status": "decremented", "data": current_data}

    # Custom actions should be added here by the agent
    # Example:
    # elif action == "feed_pet":
    #     current_data["pet"]["hunger"] = min(100, current_data.get("pet", {}).get("hunger", 50) + 25)
    #     state.data = current_data
    #     db.commit()
    #     return {"status": "fed", "data": current_data}

    else:
        # Unknown action - return current state without changes
        logger.warning(f"[Routes] Unknown action: {action}")
        return {"status": "unknown_action", "action": action, "data": current_data}


# ============================================================================
# Item CRUD Routes (Example for list-based data)
# ============================================================================


@router.get("/items")
def list_items(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Get all items, ordered by their order field."""
    items = db.query(Item).order_by(Item.order, Item.id).all()
    return [item.to_dict() for item in items]


@router.post("/items")
def create_item(data: ItemCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Create a new item."""
    # Get max order to put new item at end
    max_order = db.query(Item).count()
    item = Item(
        title=data.title,
        description=data.description,
        extra_data=data.extra_data or {},
        order=max_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info(f"[Routes] Created item: {item.id}")
    return item.to_dict()


@router.post("/items/bulk")
def create_items_bulk(
    items: List[ItemCreate], db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Create many items in one request (single transaction).

    Every list resource should have a bulk endpoint like this — one request
    for N records instead of N requests. Keep this pattern when replacing
    the Item model with real resources.
    """
    max_order = db.query(Item).count()
    created = []
    for offset, data in enumerate(items):
        item = Item(
            title=data.title,
            description=data.description,
            extra_data=data.extra_data or {},
            order=max_order + offset,
        )
        db.add(item)
        created.append(item)
    db.commit()
    for item in created:
        db.refresh(item)
    logger.info(f"[Routes] Bulk-created {len(created)} items")
    return {"created": len(created), "items": [i.to_dict() for i in created]}


@router.get("/items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get a specific item by ID."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item.to_dict()


@router.put("/items/{item_id}")
def update_item(
    item_id: int, data: ItemUpdate, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Update an existing item."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if data.title is not None:
        item.title = data.title
    if data.description is not None:
        item.description = data.description
    if data.completed is not None:
        item.completed = data.completed
    if data.order is not None:
        item.order = data.order
    if data.extra_data is not None:
        item.extra_data = data.extra_data

    db.commit()
    db.refresh(item)
    logger.info(f"[Routes] Updated item: {item_id}")
    return item.to_dict()


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)) -> Dict[str, str]:
    """Delete an item."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    db.delete(item)
    db.commit()
    logger.info(f"[Routes] Deleted item: {item_id}")
    return {"status": "deleted", "id": str(item_id)}


# ============================================================================
# UI Observation Routes (Agent API)
# ============================================================================


@router.get("/ui-snapshot")
def get_ui_snapshot(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get the current UI snapshot.

    Returns the latest UI state captured by the frontend.
    Agent uses this to observe the UI without WebSocket.

    Response includes:
    - htmlStructure: Simplified DOM structure
    - visibleText: Array of visible text on screen
    - inputValues: Current form field values
    - componentState: State of registered components
    - currentView: Current route/view
    - viewport: Window dimensions and scroll position
    - timestamp: When the snapshot was captured
    """
    snapshot = db.query(UISnapshot).first()
    if not snapshot:
        return {
            "htmlStructure": None,
            "visibleText": [],
            "inputValues": {},
            "componentState": {},
            "currentView": None,
            "viewport": {},
            "timestamp": None,
            "status": "no_snapshot",
        }
    return snapshot.to_dict()


@router.post("/ui-snapshot")
def update_ui_snapshot(
    data: UISnapshotUpdate, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Update the UI snapshot.

    Frontend calls this periodically to report UI state.
    This replaces WebSocket-based state reporting.
    """
    snapshot = db.query(UISnapshot).first()
    if not snapshot:
        snapshot = UISnapshot()
        db.add(snapshot)

    if data.htmlStructure is not None:
        snapshot.html_structure = data.htmlStructure
    if data.visibleText is not None:
        snapshot.visible_text = data.visibleText
    if data.inputValues is not None:
        snapshot.input_values = data.inputValues
    if data.componentState is not None:
        snapshot.component_state = data.componentState
    if data.currentView is not None:
        snapshot.current_view = data.currentView
    if data.viewport is not None:
        snapshot.viewport = data.viewport

    snapshot.timestamp = datetime.utcnow()

    db.commit()
    db.refresh(snapshot)
    logger.info("[Routes] UI snapshot updated")
    return snapshot.to_dict()


@router.get("/ui-screenshot")
def get_ui_screenshot(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get the current UI screenshot.

    Returns the latest screenshot captured by the frontend as base64 PNG.
    Agent uses this for visual observation of the UI.

    Response includes:
    - imageData: Base64 encoded PNG image
    - width: Image width in pixels
    - height: Image height in pixels
    - timestamp: When the screenshot was captured

    To use the image:
    - Decode base64: base64.b64decode(imageData)
    - Or display in HTML: <img src="data:image/png;base64,{imageData}">
    """
    screenshot = db.query(UIScreenshot).first()
    if not screenshot or not screenshot.image_data:
        return {
            "imageData": None,
            "width": None,
            "height": None,
            "timestamp": None,
            "status": "no_screenshot",
        }
    return screenshot.to_dict()


@router.post("/ui-screenshot")
def update_ui_screenshot(
    data: UIScreenshotUpdate, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Update the UI screenshot.

    Frontend calls this to post a screenshot of the current UI.
    Screenshot should be a base64 encoded PNG.
    """
    screenshot = db.query(UIScreenshot).first()
    if not screenshot:
        screenshot = UIScreenshot()
        db.add(screenshot)

    screenshot.image_data = data.imageData
    screenshot.width = data.width
    screenshot.height = data.height
    screenshot.timestamp = datetime.utcnow()

    db.commit()
    db.refresh(screenshot)
    logger.info(f"[Routes] UI screenshot updated ({data.width}x{data.height})")
    return {"status": "updated", "timestamp": screenshot.timestamp.isoformat()}
