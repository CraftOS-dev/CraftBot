# -*- coding: utf-8 -*-
"""
Profiler Module - Comprehensive performance tracking for the agent.

This module provides decorators and utilities for tracking execution time
of various operations in the agent loop, including:
- LLM calls
- Action retrieval and execution
- ChromaDB searches
- Trigger operations
- Agent loop iterations

The profiler supports both sync and async functions and generates
easy-to-visualize reports showing performance metrics.

Configuration:
    Profiling can be enabled/disabled via the config file at:
    decorators/profiler_config.json

    Example config:
    {
        "enabled": true,
        "auto_save_interval": 5,
        "log_dir": "decorators/logs"
    }

    Set "enabled" to true to turn on profiling.
    Set "auto_save_interval" to N to save after every N loops (0 = only at exit).
"""

import atexit
import asyncio
import functools
import json
import statistics
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union
import psutil


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_CONFIG = {
    "enabled": False,  # Disabled by default - user must explicitly enable
    "auto_save_interval": 5,  # Save every N loops (0 = only at exit)
    "log_dir": "decorators/logs",
}

CONFIG_PATH = Path(__file__).parent / "profiler_config.json"


def _load_profiler_config() -> Dict[str, Any]:
    """Load profiler configuration from file."""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            config.update(user_config)
        except Exception:
            pass  # Use defaults if config is invalid
    return config


def _save_profiler_config(config: Dict[str, Any]) -> None:
    """Save profiler configuration to file."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


class OperationCategory(str, Enum):
    """Categories for profiled operations."""
    AGENT_LOOP = "agent_loop"
    LLM = "llm"
    ACTION_ROUTING = "action_routing"
    ACTION_EXECUTION = "action_execution"
    ACTION_LIBRARY = "action_library"
    TRIGGER = "trigger"
    DATABASE = "database"
    CONTEXT = "context"
    REASONING = "reasoning"
    OTHER = "other"


@dataclass
class ProfileRecord:
    """A single profiling record for an operation."""
    timestamp: float
    name: str
    category: str
    duration_ms: float
    loop_id: Optional[str] = None
    loop_number: Optional[int] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OperationStats:
    """Aggregated statistics for a single operation type."""
    name: str
    category: str
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float('inf')
    max_ms: float = 0.0
    durations: List[float] = field(default_factory=list)

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count > 0 else 0.0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.durations) if self.durations else 0.0

    @property
    def std_dev_ms(self) -> float:
        return statistics.stdev(self.durations) if len(self.durations) > 1 else 0.0

    def add_duration(self, duration_ms: float) -> None:
        self.count += 1
        self.total_ms += duration_ms
        self.min_ms = min(self.min_ms, duration_ms)
        self.max_ms = max(self.max_ms, duration_ms)
        self.durations.append(duration_ms)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "count": self.count,
            "total_ms": round(self.total_ms, 3),
            "avg_ms": round(self.avg_ms, 3),
            "min_ms": round(self.min_ms, 3) if self.min_ms != float('inf') else 0.0,
            "max_ms": round(self.max_ms, 3),
            "median_ms": round(self.median_ms, 3),
            "std_dev_ms": round(self.std_dev_ms, 3),
        }


@dataclass
class LoopStats:
    """Statistics for a single agent loop iteration."""
    loop_id: str
    loop_number: int
    start_time: float
    end_time: Optional[float] = None
    operations: List[ProfileRecord] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000

    def add_operation(self, record: ProfileRecord) -> None:
        self.operations.append(record)

    def get_breakdown(self) -> Dict[str, float]:
        """Get time breakdown by category."""
        breakdown: Dict[str, float] = defaultdict(float)
        for op in self.operations:
            breakdown[op.category] += op.duration_ms
        return dict(breakdown)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "loop_number": self.loop_number,
            "duration_ms": round(self.duration_ms, 3),
            "operation_count": len(self.operations),
            "breakdown_by_category": {k: round(v, 3) for k, v in self.get_breakdown().items()},
        }


class AgentProfiler:
    """
    Comprehensive profiler for tracking agent performance.

    Features:
    - Tracks individual operations with timing and metadata
    - Aggregates statistics by operation name and category
    - Tracks per-loop performance metrics
    - Thread-safe logging
    - Generates human-readable and JSON reports
    - Auto-saves at configurable intervals and on exit

    Configuration is loaded from decorators/profiler_config.json:
    {
        "enabled": true,    # Set to true to enable profiling
        "auto_save_interval": 5,  # Save every N loops (0 = only at exit)
        "log_dir": "decorators/logs"
    }
    """

    _instance: Optional["AgentProfiler"] = None
    _lock = threading.Lock()
    _atexit_registered = False

    def __new__(cls, *args, **kwargs) -> "AgentProfiler":
        """Singleton pattern for global profiler access."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, log_dir: str | None = None, enabled: bool | None = None) -> None:
        if self._initialized:
            return

        # Load config from file
        config = _load_profiler_config()

        # Use config values, allow override via constructor
        self.enabled = enabled if enabled is not None else config.get("enabled", False)
        self._auto_save_interval = config.get("auto_save_interval", 5)
        log_dir = log_dir or config.get("log_dir", "decorators/logs")

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique session ID
        self.session_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        self.log_path = self.log_dir / f"profile_{self.session_id}.json"

        # Thread safety
        self._write_lock = threading.Lock()

        # Storage
        self._records: List[ProfileRecord] = []
        self._stats: Dict[str, OperationStats] = {}
        self._category_stats: Dict[str, OperationStats] = {}
        self._loops: Dict[str, LoopStats] = {}

        # Current loop tracking
        self._current_loop_id: Optional[str] = None
        self._loop_counter = 0
        self._last_save_loop = 0

        # Session metadata
        self._session_start = time.time()
        self._has_data = False  # Track if we have any data to save

        self._initialized = True

        # Register atexit handler (only once)
        if not AgentProfiler._atexit_registered:
            atexit.register(self._atexit_save)
            AgentProfiler._atexit_registered = True

    def _atexit_save(self) -> None:
        """Save profiling data on process exit."""
        if self._has_data and self.enabled:
            try:
                self.save_report()
                self.save_json()
            except Exception:
                pass  # Silently fail on exit

    @classmethod
    def get_instance(cls) -> "AgentProfiler":
        """Get the singleton profiler instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the profiler instance (useful for testing)."""
        with cls._lock:
            if cls._instance and cls._instance._has_data:
                try:
                    cls._instance.save_report()
                    cls._instance.save_json()
                except Exception:
                    pass
            cls._instance = None

    def enable(self) -> None:
        """Enable profiling and update config file."""
        self.enabled = True
        config = _load_profiler_config()
        config["enabled"] = True
        _save_profiler_config(config)

    def disable(self) -> None:
        """Disable profiling and update config file."""
        self.enabled = False
        config = _load_profiler_config()
        config["enabled"] = False
        _save_profiler_config(config)

    # =========================================================================
    # Loop Management
    # =========================================================================

    def start_loop(self, loop_id: Optional[str] = None) -> str:
        """
        Mark the start of an agent loop iteration.

        Args:
            loop_id: Optional custom loop identifier. Auto-generated if not provided.

        Returns:
            The loop ID for this iteration.
        """
        if not self.enabled:
            return ""

        self._loop_counter += 1
        loop_id = loop_id or f"loop_{self._loop_counter}_{uuid.uuid4().hex[:6]}"

        with self._write_lock:
            self._current_loop_id = loop_id
            self._loops[loop_id] = LoopStats(
                loop_id=loop_id,
                loop_number=self._loop_counter,
                start_time=time.time(),
            )

        return loop_id

    def end_loop(self, loop_id: Optional[str] = None) -> None:
        """
        Mark the end of an agent loop iteration.

        Args:
            loop_id: The loop ID to end. Uses current loop if not provided.
        """
        if not self.enabled:
            return

        loop_id = loop_id or self._current_loop_id
        if not loop_id or loop_id not in self._loops:
            return

        with self._write_lock:
            self._loops[loop_id].end_time = time.time()
            if self._current_loop_id == loop_id:
                self._current_loop_id = None

        # Auto-save if interval is configured
        if self._auto_save_interval > 0:
            loops_since_save = self._loop_counter - self._last_save_loop
            if loops_since_save >= self._auto_save_interval:
                self._auto_save()

    # =========================================================================
    # Recording
    # =========================================================================

    def _auto_save(self) -> None:
        """Auto-save profiling data to disk."""
        try:
            self.save_json()
            self.save_report()
            self._last_save_loop = self._loop_counter
        except Exception:
            pass  # Silently fail auto-save

    def record(
        self,
        name: str,
        duration_ms: float,
        category: Union[OperationCategory, str] = OperationCategory.OTHER,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a profiling entry.

        Args:
            name: Name of the operation.
            duration_ms: Duration in milliseconds.
            category: Operation category for grouping.
            meta: Additional metadata to store.
        """
        if not self.enabled:
            return

        if isinstance(category, OperationCategory):
            category = category.value

        # Get resource usage
        try:
            process = psutil.Process()
            cpu_percent = process.cpu_percent(interval=None)
            memory_mb = process.memory_info().rss / 1e6
        except Exception:
            cpu_percent = None
            memory_mb = None

        record = ProfileRecord(
            timestamp=time.time(),
            name=name,
            category=category,
            duration_ms=round(duration_ms, 3),
            loop_id=self._current_loop_id,
            loop_number=self._loop_counter if self._current_loop_id else None,
            cpu_percent=cpu_percent,
            memory_mb=round(memory_mb, 3) if memory_mb else None,
            meta=meta or {},
        )

        with self._write_lock:
            self._records.append(record)
            self._has_data = True  # Mark that we have data to save

            # Update operation stats
            if name not in self._stats:
                self._stats[name] = OperationStats(name=name, category=category)
            self._stats[name].add_duration(duration_ms)

            # Update category stats
            if category not in self._category_stats:
                self._category_stats[category] = OperationStats(name=category, category=category)
            self._category_stats[category].add_duration(duration_ms)

            # Add to current loop if active
            if self._current_loop_id and self._current_loop_id in self._loops:
                self._loops[self._current_loop_id].add_operation(record)

    # =========================================================================
    # Reporting
    # =========================================================================

    def get_stats(self) -> Dict[str, OperationStats]:
        """Get all operation statistics."""
        return dict(self._stats)

    def get_category_stats(self) -> Dict[str, OperationStats]:
        """Get statistics grouped by category."""
        return dict(self._category_stats)

    def get_loop_stats(self) -> List[LoopStats]:
        """Get statistics for all completed loops."""
        return [loop for loop in self._loops.values() if loop.end_time is not None]

    def get_slowest_operations(self, n: int = 10) -> List[Dict[str, Any]]:
        """Get the N slowest operations by average time."""
        sorted_stats = sorted(
            self._stats.values(),
            key=lambda x: x.avg_ms,
            reverse=True
        )
        return [s.to_dict() for s in sorted_stats[:n]]

    def get_most_called_operations(self, n: int = 10) -> List[Dict[str, Any]]:
        """Get the N most frequently called operations."""
        sorted_stats = sorted(
            self._stats.values(),
            key=lambda x: x.count,
            reverse=True
        )
        return [s.to_dict() for s in sorted_stats[:n]]

    def generate_report(self) -> str:
        """
        Generate a human-readable performance report.

        Returns:
            Formatted string report.
        """
        lines = []
        lines.append("=" * 80)
        lines.append("AGENT PERFORMANCE PROFILING REPORT")
        lines.append("=" * 80)
        lines.append(f"Session ID: {self.session_id}")
        lines.append(f"Generated at: {datetime.now().isoformat()}")
        lines.append(f"Total duration: {(time.time() - self._session_start) * 1000:.1f}ms")
        lines.append(f"Total operations recorded: {len(self._records)}")
        lines.append(f"Agent loops completed: {len(self.get_loop_stats())}")
        lines.append("")

        # Category summary
        lines.append("-" * 80)
        lines.append("TIME BY CATEGORY")
        lines.append("-" * 80)
        lines.append(f"{'Category':<25} {'Count':>8} {'Total (ms)':>12} {'Avg (ms)':>10} {'Min (ms)':>10} {'Max (ms)':>10}")
        lines.append("-" * 80)

        for cat_name, cat_stats in sorted(self._category_stats.items(), key=lambda x: x[1].total_ms, reverse=True):
            lines.append(
                f"{cat_name:<25} {cat_stats.count:>8} {cat_stats.total_ms:>12.1f} "
                f"{cat_stats.avg_ms:>10.1f} {cat_stats.min_ms if cat_stats.min_ms != float('inf') else 0:>10.1f} {cat_stats.max_ms:>10.1f}"
            )
        lines.append("")

        # Top 15 slowest operations by average
        lines.append("-" * 80)
        lines.append("TOP 15 SLOWEST OPERATIONS (by average time)")
        lines.append("-" * 80)
        lines.append(f"{'Operation':<40} {'Category':<15} {'Count':>6} {'Avg (ms)':>10} {'Total (ms)':>12}")
        lines.append("-" * 80)

        for stat in self.get_slowest_operations(15):
            op_name = stat["name"][:38] + ".." if len(stat["name"]) > 40 else stat["name"]
            lines.append(
                f"{op_name:<40} {stat['category']:<15} {stat['count']:>6} "
                f"{stat['avg_ms']:>10.1f} {stat['total_ms']:>12.1f}"
            )
        lines.append("")

        # Top 10 most called operations
        lines.append("-" * 80)
        lines.append("TOP 10 MOST CALLED OPERATIONS")
        lines.append("-" * 80)
        lines.append(f"{'Operation':<40} {'Category':<15} {'Count':>6} {'Avg (ms)':>10} {'Total (ms)':>12}")
        lines.append("-" * 80)

        for stat in self.get_most_called_operations(10):
            op_name = stat["name"][:38] + ".." if len(stat["name"]) > 40 else stat["name"]
            lines.append(
                f"{op_name:<40} {stat['category']:<15} {stat['count']:>6} "
                f"{stat['avg_ms']:>10.1f} {stat['total_ms']:>12.1f}"
            )
        lines.append("")

        # Loop statistics
        loop_stats = self.get_loop_stats()
        if loop_stats:
            lines.append("-" * 80)
            lines.append("AGENT LOOP STATISTICS")
            lines.append("-" * 80)

            loop_durations = [l.duration_ms for l in loop_stats]
            lines.append(f"Total loops: {len(loop_stats)}")
            lines.append(f"Average loop duration: {statistics.mean(loop_durations):.1f}ms")
            lines.append(f"Min loop duration: {min(loop_durations):.1f}ms")
            lines.append(f"Max loop duration: {max(loop_durations):.1f}ms")
            if len(loop_durations) > 1:
                lines.append(f"Std dev: {statistics.stdev(loop_durations):.1f}ms")
            lines.append("")

            # Show individual loop breakdown (last 10 loops)
            lines.append("Last 10 Loop Breakdowns:")
            lines.append("-" * 80)
            lines.append(f"{'Loop #':<8} {'Duration (ms)':>14} {'Operations':>12} {'Breakdown'}")
            lines.append("-" * 80)

            for loop in loop_stats[-10:]:
                breakdown_str = ", ".join(
                    f"{k}: {v:.0f}ms" for k, v in sorted(loop.get_breakdown().items(), key=lambda x: x[1], reverse=True)[:4]
                )
                lines.append(
                    f"{loop.loop_number:<8} {loop.duration_ms:>14.1f} {len(loop.operations):>12} {breakdown_str}"
                )
            lines.append("")

            # Check for performance degradation over time
            if len(loop_durations) >= 5:
                first_half = loop_durations[:len(loop_durations)//2]
                second_half = loop_durations[len(loop_durations)//2:]
                avg_first = statistics.mean(first_half)
                avg_second = statistics.mean(second_half)

                if avg_second > avg_first * 1.2:  # 20% slower
                    pct_slower = ((avg_second - avg_first) / avg_first) * 100
                    lines.append(f"⚠️  PERFORMANCE DEGRADATION DETECTED")
                    lines.append(f"    Later loops are {pct_slower:.1f}% slower than earlier loops")
                    lines.append(f"    First half avg: {avg_first:.1f}ms, Second half avg: {avg_second:.1f}ms")
                    lines.append("")

        # All operations detail
        lines.append("-" * 80)
        lines.append("ALL OPERATIONS DETAIL")
        lines.append("-" * 80)
        lines.append(f"{'Operation':<45} {'Cat':<12} {'Count':>6} {'Avg':>8} {'Min':>8} {'Max':>8} {'Total':>10}")
        lines.append("-" * 80)

        for stat in sorted(self._stats.values(), key=lambda x: x.total_ms, reverse=True):
            op_name = stat.name[:43] + ".." if len(stat.name) > 45 else stat.name
            cat_short = stat.category[:10] + ".." if len(stat.category) > 12 else stat.category
            min_val = stat.min_ms if stat.min_ms != float('inf') else 0
            lines.append(
                f"{op_name:<45} {cat_short:<12} {stat.count:>6} {stat.avg_ms:>8.1f} "
                f"{min_val:>8.1f} {stat.max_ms:>8.1f} {stat.total_ms:>10.1f}"
            )

        lines.append("")
        lines.append("=" * 80)
        lines.append("END OF REPORT")
        lines.append("=" * 80)

        return "\n".join(lines)

    def save_report(self, filename: Optional[str] = None) -> Path:
        """
        Save the report to a file.

        Args:
            filename: Optional custom filename. Auto-generated if not provided.

        Returns:
            Path to the saved report file.
        """
        if filename is None:
            filename = f"profile_report_{self.session_id}.txt"

        report_path = self.log_dir / filename
        report_path.write_text(self.generate_report(), encoding="utf-8")
        return report_path

    def save_json(self, filename: Optional[str] = None) -> Path:
        """
        Save all profiling data to a JSON file.

        Args:
            filename: Optional custom filename. Auto-generated if not provided.

        Returns:
            Path to the saved JSON file.
        """
        if filename is None:
            filename = f"profile_data_{self.session_id}.json"

        data = {
            "session_id": self.session_id,
            "generated_at": datetime.now().isoformat(),
            "total_duration_ms": (time.time() - self._session_start) * 1000,
            "operation_stats": {k: v.to_dict() for k, v in self._stats.items()},
            "category_stats": {k: v.to_dict() for k, v in self._category_stats.items()},
            "loop_stats": [l.to_dict() for l in self.get_loop_stats()],
            "records": [r.to_dict() for r in self._records],
        }

        json_path = self.log_dir / filename
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return json_path

    def print_report(self) -> None:
        """Print the report to stdout."""
        print(self.generate_report())

    def clear(self) -> None:
        """Clear all recorded data."""
        with self._write_lock:
            self._records.clear()
            self._stats.clear()
            self._category_stats.clear()
            self._loops.clear()
            self._current_loop_id = None
            self._loop_counter = 0
            self._session_start = time.time()


# =============================================================================
# Global profiler instance
# =============================================================================
profiler = AgentProfiler.get_instance()


# =============================================================================
# Decorator functions
# =============================================================================

F = TypeVar("F", bound=Callable[..., Any])


def profile(
    name: Optional[str] = None,
    category: Union[OperationCategory, str] = OperationCategory.OTHER,
    meta_fn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Callable[[F], F]:
    """
    Decorator that profiles function execution time.

    Automatically handles both sync and async functions.

    Args:
        name: Operation name for the record. Uses function name if not provided.
        category: Category for grouping operations.
        meta_fn: Optional function to extract metadata from the result.
                 Signature: meta_fn(result, *args, **kwargs) -> Dict[str, Any]

    Example:
        @profile("llm_call", OperationCategory.LLM)
        async def generate_response(self, prompt):
            ...

        @profile(category=OperationCategory.ACTION_EXECUTION)
        def execute_action(self, action):
            ...
    """
    def decorator(fn: F) -> F:
        op_name = name or fn.__name__

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            if not profiler.enabled:
                return await fn(*args, **kwargs)

            start = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
                return result
            finally:
                end = time.perf_counter()
                duration_ms = (end - start) * 1000
                meta = meta_fn(result, *args, **kwargs) if meta_fn else None
                profiler.record(op_name, duration_ms, category, meta)

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            if not profiler.enabled:
                return fn(*args, **kwargs)

            start = time.perf_counter()
            result = None
            try:
                result = fn(*args, **kwargs)
                return result
            finally:
                end = time.perf_counter()
                duration_ms = (end - start) * 1000
                meta = meta_fn(result, *args, **kwargs) if meta_fn and result is not None else None
                profiler.record(op_name, duration_ms, category, meta)

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def profile_loop(fn: F) -> F:
    """
    Decorator specifically for profiling the main agent loop (react method).

    This decorator:
    - Starts/ends loop tracking
    - Records the total loop time

    Example:
        @profile_loop
        async def react(self, trigger):
            ...
    """
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        if not profiler.enabled:
            return await fn(*args, **kwargs)

        loop_id = profiler.start_loop()
        start = time.perf_counter()
        try:
            result = await fn(*args, **kwargs)
            return result
        finally:
            end = time.perf_counter()
            duration_ms = (end - start) * 1000
            profiler.record("react_loop_total", duration_ms, OperationCategory.AGENT_LOOP)
            profiler.end_loop(loop_id)

    return wrapper  # type: ignore


class ProfileContext:
    """
    Context manager for profiling a code block.

    Example:
        async with ProfileContext("my_operation", OperationCategory.LLM):
            # code to profile
            await some_async_operation()
    """

    def __init__(
        self,
        name: str,
        category: Union[OperationCategory, str] = OperationCategory.OTHER,
        meta: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.category = category
        self.meta = meta
        self.start_time: Optional[float] = None

    async def __aenter__(self) -> "ProfileContext":
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.start_time and profiler.enabled:
            duration_ms = (time.perf_counter() - self.start_time) * 1000
            profiler.record(self.name, duration_ms, self.category, self.meta)

    def __enter__(self) -> "ProfileContext":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.start_time and profiler.enabled:
            duration_ms = (time.perf_counter() - self.start_time) * 1000
            profiler.record(self.name, duration_ms, self.category, self.meta)


# =============================================================================
# Utility functions
# =============================================================================

def enable_profiling() -> None:
    """
    Enable the global profiler and persist the setting to config file.

    This will:
    1. Enable profiling for the current session
    2. Update decorators/profiler_config.json so future sessions start with profiling enabled
    """
    profiler.enable()


def disable_profiling() -> None:
    """
    Disable the global profiler and persist the setting to config file.

    This will:
    1. Disable profiling for the current session
    2. Update decorators/profiler_config.json so future sessions start with profiling disabled
    """
    profiler.disable()


def is_profiling_enabled() -> bool:
    """Check if profiling is currently enabled."""
    return profiler.enabled


def set_auto_save_interval(interval: int) -> None:
    """
    Set how often to auto-save profiling data (in number of loops).

    Args:
        interval: Number of loops between auto-saves. Set to 0 to only save at exit.
    """
    profiler._auto_save_interval = interval
    config = _load_profiler_config()
    config["auto_save_interval"] = interval
    _save_profiler_config(config)


def print_profile_report() -> None:
    """Print the profiling report to stdout."""
    profiler.print_report()


def save_profile_report() -> Path:
    """Save the profiling report and return the path."""
    txt_path = profiler.save_report()
    json_path = profiler.save_json()
    print(f"Profile report saved to: {txt_path}")
    print(f"Profile data saved to: {json_path}")
    return txt_path


def get_profiler() -> AgentProfiler:
    """Get the global profiler instance."""
    return profiler


def get_profiler_config() -> Dict[str, Any]:
    """
    Get the current profiler configuration.

    Returns:
        Dict with keys: enabled, auto_save_interval, log_dir
    """
    return _load_profiler_config()


# Backward compatibility with old API
def log_events(name: str = None):
    """Legacy decorator - redirects to profile decorator."""
    return profile(name=name, category=OperationCategory.OTHER)
