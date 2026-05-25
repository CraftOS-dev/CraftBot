"""Interface adapters for UI layer."""

from app.ui_layer.adapters.base import InterfaceAdapter
from app.ui_layer.adapters.cli_adapter import CLIAdapter
from app.ui_layer.adapters.browser_adapter import BrowserAdapter

__all__ = ["InterfaceAdapter", "CLIAdapter", "BrowserAdapter"]
