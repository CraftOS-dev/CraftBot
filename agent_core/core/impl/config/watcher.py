# -*- coding: utf-8 -*-
"""
Config Watcher Module

Watches configuration files for changes and triggers hot-reload automatically.
Uses watchdog library for efficient file system monitoring.
"""

import asyncio
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass

from agent_core.utils.logger import logger

# Try to import watchdog, fall back to polling if not available
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning("[CONFIG_WATCHER] watchdog not installed, using polling fallback")


@dataclass
class WatchedConfig:
    """Configuration for a watched file."""
    path: Path
    reload_callback: Callable[[], Any]
    last_modified: float = 0.0


class ConfigFileHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """Handler for file system events."""

    def __init__(self, watcher: "ConfigWatcher"):
        if WATCHDOG_AVAILABLE:
            super().__init__()
        self._watcher = watcher
        self._debounce_timers: Dict[str, threading.Timer] = {}
        self._debounce_delay = 0.5  # seconds

    def on_modified(self, event):
        """Handle file modification event."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        self._watcher._handle_file_change(file_path)

    def _debounced_reload(self, file_path: Path):
        """Debounce rapid file changes."""
        path_str = str(file_path)

        # Cancel existing timer if any
        if path_str in self._debounce_timers:
            self._debounce_timers[path_str].cancel()

        # Create new timer
        timer = threading.Timer(
            self._debounce_delay,
            lambda: self._watcher._trigger_reload(file_path)
        )
        self._debounce_timers[path_str] = timer
        timer.start()


class ConfigWatcher:
    """
    Watches configuration files for changes and triggers hot-reload.

    Supports watching:
    - settings.json
    - mcp_config.json
    - skills_config.json
    - external_comms_config.json

    When a file changes, the appropriate reload callback is invoked.
    """

    _instance: Optional["ConfigWatcher"] = None

    def __new__(cls) -> "ConfigWatcher":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._watched_configs: Dict[str, WatchedConfig] = {}
        self._observer: Optional[Any] = None
        self._handler: Optional[ConfigFileHandler] = None
        self._running = False
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._debounce_timers: Dict[str, threading.Timer] = {}
        self._debounce_delay = 0.5  # seconds
        self._initialized = True

    def register(
        self,
        config_path: Path,
        reload_callback: Callable[[], Any],
        name: Optional[str] = None
    ) -> None:
        """
        Register a config file to watch.

        Args:
            config_path: Path to the config file
            reload_callback: Async or sync function to call when file changes
            name: Optional name for logging
        """
        config_path = Path(config_path).resolve()
        name = name or config_path.name

        self._watched_configs[str(config_path)] = WatchedConfig(
            path=config_path,
            reload_callback=reload_callback,
            last_modified=config_path.stat().st_mtime if config_path.exists() else 0.0
        )

        logger.info(f"[CONFIG_WATCHER] Registered watch for {name}: {config_path}")

    def start(self, event_loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """
        Start watching for file changes.

        Args:
            event_loop: Event loop to use for async callbacks
        """
        if self._running:
            return

        self._event_loop = event_loop

        if WATCHDOG_AVAILABLE:
            self._start_watchdog()
        else:
            self._start_polling()

        self._running = True
        logger.info("[CONFIG_WATCHER] Started watching config files")

    def _start_watchdog(self) -> None:
        """Start using watchdog observer."""
        self._handler = ConfigFileHandler(self)
        self._observer = Observer()

        # Watch each config file's parent directory
        watched_dirs = set()
        for config in self._watched_configs.values():
            parent_dir = config.path.parent
            if parent_dir not in watched_dirs:
                self._observer.schedule(self._handler, str(parent_dir), recursive=False)
                watched_dirs.add(parent_dir)
                logger.debug(f"[CONFIG_WATCHER] Watching directory: {parent_dir}")

        self._observer.start()

    def _start_polling(self) -> None:
        """Start polling-based file watching (fallback)."""
        def poll_loop():
            import time
            while self._running:
                for path_str, config in self._watched_configs.items():
                    try:
                        if config.path.exists():
                            mtime = config.path.stat().st_mtime
                            if mtime > config.last_modified:
                                config.last_modified = mtime
                                self._trigger_reload(config.path)
                    except Exception as e:
                        logger.debug(f"[CONFIG_WATCHER] Poll error for {path_str}: {e}")
                time.sleep(1.0)  # Poll every second

        thread = threading.Thread(target=poll_loop, daemon=True)
        thread.start()

    def stop(self) -> None:
        """Stop watching for file changes."""
        self._running = False

        if WATCHDOG_AVAILABLE and self._observer:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None

        # Cancel any pending debounce timers
        for timer in self._debounce_timers.values():
            timer.cancel()
        self._debounce_timers.clear()

        logger.info("[CONFIG_WATCHER] Stopped watching config files")

    def _handle_file_change(self, file_path: Path) -> None:
        """Handle a file change event with debouncing."""
        path_str = str(file_path.resolve())

        # Check if this file is being watched
        if path_str not in self._watched_configs:
            return

        # Cancel existing timer if any
        if path_str in self._debounce_timers:
            self._debounce_timers[path_str].cancel()

        # Create new debounced timer
        timer = threading.Timer(
            self._debounce_delay,
            lambda: self._trigger_reload(file_path)
        )
        self._debounce_timers[path_str] = timer
        timer.start()

    def _trigger_reload(self, file_path: Path) -> None:
        """Trigger the reload callback for a config file."""
        path_str = str(file_path.resolve())

        if path_str not in self._watched_configs:
            return

        config = self._watched_configs[path_str]
        logger.info(f"[CONFIG_WATCHER] Detected change in {file_path.name}, triggering reload")

        try:
            callback = config.reload_callback

            # Check if callback is async
            if asyncio.iscoroutinefunction(callback):
                if self._event_loop and self._event_loop.is_running():
                    # Schedule in the event loop
                    asyncio.run_coroutine_threadsafe(callback(), self._event_loop)
                else:
                    # Create new event loop for this thread
                    asyncio.run(callback())
            else:
                # Sync callback
                callback()

            # Update last modified time
            if config.path.exists():
                config.last_modified = config.path.stat().st_mtime

            logger.info(f"[CONFIG_WATCHER] Reload complete for {file_path.name}")

        except Exception as e:
            logger.error(f"[CONFIG_WATCHER] Reload failed for {file_path.name}: {e}")
            import traceback
            logger.debug(traceback.format_exc())


# Global singleton instance
config_watcher = ConfigWatcher()
