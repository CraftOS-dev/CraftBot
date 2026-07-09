"""
Living UI System Models (SYSTEM-MANAGED — do not edit)

The declarative Base plus the models that power the agent observation API
(/state, /ui-snapshot, /ui-screenshot). These are infrastructure: every
Living UI has them, no app may remove them, and the agent never edits this
file.

App data models do NOT live here — they are materialized by the engine
(engine.py) from config/schema.json. See models.py.

NOTE the `default=1` primary keys here are a SINGLETON pattern (each of
these tables holds exactly one row). It is correct ONLY for these system
tables — app entities get proper autoincrement ids from the engine.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from typing import Dict, Any

Base = declarative_base()


class AppState(Base):
    """
    Flexible application state storage.

    Stores the entire app state as JSON, allowing any structure.
    This is the primary model used by the default state management.
    """

    __tablename__ = "app_state"

    id = Column(Integer, primary_key=True, default=1)  # singleton row
    data = Column(JSON, default=dict)  # Stores arbitrary state as JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "data": self.data or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }

    def update_data(self, updates: Dict[str, Any]) -> None:
        """Merge updates into existing data."""
        current = self.data or {}
        current.update(updates)
        self.data = current
        self.updated_at = datetime.utcnow()


class UISnapshot(Base):
    """
    UI state snapshot for agent observation.

    Frontend periodically posts UI state here.
    Agent can GET this to observe the UI without WebSocket.
    """

    __tablename__ = "ui_snapshot"

    id = Column(Integer, primary_key=True, default=1)  # singleton row
    html_structure = Column(Text, nullable=True)  # Simplified DOM structure
    visible_text = Column(JSON, default=list)  # Array of visible text content
    input_values = Column(JSON, default=dict)  # Form field values
    component_state = Column(JSON, default=dict)  # Registered component states
    current_view = Column(String(255), nullable=True)  # Current route/view
    viewport = Column(JSON, default=dict)  # Window dimensions, scroll position
    timestamp = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "htmlStructure": self.html_structure,
            "visibleText": self.visible_text or [],
            "inputValues": self.input_values or {},
            "componentState": self.component_state or {},
            "currentView": self.current_view,
            "viewport": self.viewport or {},
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class UIScreenshot(Base):
    """
    UI screenshot for agent visual observation.

    Frontend captures and posts screenshot here.
    Agent can GET this to see the UI visually.
    """

    __tablename__ = "ui_screenshot"

    id = Column(Integer, primary_key=True, default=1)  # singleton row
    image_data = Column(Text, nullable=True)  # Base64 encoded PNG
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "imageData": self.image_data,
            "width": self.width,
            "height": self.height,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class StoredFile(Base):
    """
    Metadata for an uploaded file (the bytes live in the configured files
    directory — see files_routes.py). Regular autoincrement table, NOT a
    singleton.
    """

    __tablename__ = "stored_file"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)  # original filename
    stored_name = Column(String(255), nullable=False, unique=True)  # uuid.ext on disk
    mime = Column(String(127), nullable=True)
    size = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mime": self.mime,
            "size": self.size,
            "url": f"/api/files/{self.id}",
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
