# -*- coding: utf-8 -*-
"""
Database interface module for CraftBot.

Re-exports the base DatabaseInterface from agent_core which includes
parallel action logging capabilities.
"""

from agent_core.core.database_interface import DatabaseInterface

__all__ = ["DatabaseInterface"]
