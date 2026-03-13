"""Dashboard metrics collector for the browser interface."""

from __future__ import annotations

import asyncio
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor


class TimePeriod(Enum):
    """Time period for filtered metrics queries."""
    HOUR_1 = "1h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1m"
    TOTAL = "total"

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

if TYPE_CHECKING:
    from app.agent_base import AgentBase


# ─────────────────────────────────────────────────────────────────────
# Pricing Data (USD per 1M tokens)
# ─────────────────────────────────────────────────────────────────────

MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # OpenAI models
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "o1-preview": {"input": 15.00, "output": 60.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    # Anthropic models
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    # Google models
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    # Default fallback
    "default": {"input": 1.00, "output": 3.00},
}


def get_model_pricing(model: str) -> Dict[str, float]:
    """Get pricing for a model, with fuzzy matching."""
    model_lower = model.lower()
    for key, pricing in MODEL_PRICING.items():
        if key in model_lower:
            return pricing
    return MODEL_PRICING["default"]


# ─────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────

@dataclass
class LLMCallRecord:
    """Record of a single LLM call."""
    timestamp: float
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: float
    task_id: Optional[str] = None


@dataclass
class TaskRecord:
    """Record of a completed task."""
    task_id: str
    name: str
    status: str  # "completed" or "error"
    start_time: float
    end_time: float
    total_cost: float
    llm_call_count: int


@dataclass
class SystemMetrics:
    """Current system resource metrics."""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    disk_percent: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    network_sent_mb: float = 0.0
    network_recv_mb: float = 0.0
    network_sent_rate_kbps: float = 0.0
    network_recv_rate_kbps: float = 0.0


@dataclass
class ThreadPoolMetrics:
    """Thread pool utilization metrics."""
    active_threads: int = 0
    max_workers: int = 16
    pending_tasks: int = 0
    utilization_percent: float = 0.0


@dataclass
class CostMetrics:
    """Cost-related metrics."""
    cost_per_request_avg: float = 0.0
    cost_per_task_avg: float = 0.0
    cost_today: float = 0.0
    cost_this_week: float = 0.0
    cost_this_month: float = 0.0
    total_cost: float = 0.0


@dataclass
class TaskMetrics:
    """Task success/failure metrics."""
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    running_tasks: int = 0
    success_rate: float = 0.0


@dataclass
class UsageMetrics:
    """Request volume and usage patterns."""
    requests_last_hour: int = 0
    requests_today: int = 0
    peak_hour: int = 0  # 0-23
    peak_hour_requests: int = 0
    hourly_distribution: List[int] = field(default_factory=lambda: [0] * 24)


@dataclass
class TokenMetrics:
    """Token usage metrics."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    total_tokens: int = 0


@dataclass
class MCPServerInfo:
    """Information about an MCP server."""
    name: str
    status: str  # "connected", "disconnected", "error"
    tool_count: int
    transport: str = "stdio"  # "stdio", "sse", "websocket"
    action_set: str = ""
    tools: List[str] = field(default_factory=list)


@dataclass
class UsageCount:
    """Usage count for a tool or skill."""
    name: str
    count: int = 0


@dataclass
class MCPMetrics:
    """MCP server metrics."""
    total_servers: int = 0
    connected_servers: int = 0
    total_tools: int = 0
    total_calls: int = 0
    servers: List[MCPServerInfo] = field(default_factory=list)
    top_tools: List[UsageCount] = field(default_factory=list)


@dataclass
class SkillInfo:
    """Information about a skill."""
    name: str
    enabled: bool
    description: str = ""
    user_invocable: bool = True
    action_sets: List[str] = field(default_factory=list)


@dataclass
class SkillMetrics:
    """Skill metrics."""
    total_skills: int = 0
    enabled_skills: int = 0
    total_invocations: int = 0
    skills: List[SkillInfo] = field(default_factory=list)
    top_skills: List[UsageCount] = field(default_factory=list)


@dataclass
class ModelMetrics:
    """Current model information."""
    provider: str = ""
    model_id: str = ""
    model_name: str = ""  # Friendly name


@dataclass
class DashboardMetrics:
    """Complete dashboard metrics snapshot."""
    # Timing
    uptime_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)

    # Costs
    cost: CostMetrics = field(default_factory=CostMetrics)

    # Tasks
    task: TaskMetrics = field(default_factory=TaskMetrics)

    # Tokens
    token: TokenMetrics = field(default_factory=TokenMetrics)

    # System resources
    system: SystemMetrics = field(default_factory=SystemMetrics)

    # Thread pool
    thread_pool: ThreadPoolMetrics = field(default_factory=ThreadPoolMetrics)

    # Usage patterns
    usage: UsageMetrics = field(default_factory=UsageMetrics)

    # MCP servers
    mcp: MCPMetrics = field(default_factory=MCPMetrics)

    # Skills
    skill: SkillMetrics = field(default_factory=SkillMetrics)

    # Model info
    model: ModelMetrics = field(default_factory=ModelMetrics)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "uptimeSeconds": self.uptime_seconds,
            "timestamp": self.timestamp,
            "cost": {
                "perRequestAvg": round(self.cost.cost_per_request_avg, 6),
                "perTaskAvg": round(self.cost.cost_per_task_avg, 6),
                "today": round(self.cost.cost_today, 4),
                "thisWeek": round(self.cost.cost_this_week, 4),
                "thisMonth": round(self.cost.cost_this_month, 4),
                "total": round(self.cost.total_cost, 4),
            },
            "task": {
                "total": self.task.total_tasks,
                "completed": self.task.completed_tasks,
                "failed": self.task.failed_tasks,
                "running": self.task.running_tasks,
                "successRate": round(self.task.success_rate, 1),
            },
            "token": {
                "input": self.token.total_input_tokens,
                "output": self.token.total_output_tokens,
                "cached": self.token.total_cached_tokens,
                "total": self.token.total_tokens,
            },
            "system": {
                "cpuPercent": round(self.system.cpu_percent, 1),
                "memoryPercent": round(self.system.memory_percent, 1),
                "memoryUsedMb": round(self.system.memory_used_mb, 1),
                "memoryTotalMb": round(self.system.memory_total_mb, 1),
                "diskPercent": round(self.system.disk_percent, 1),
                "diskUsedGb": round(self.system.disk_used_gb, 1),
                "diskTotalGb": round(self.system.disk_total_gb, 1),
                "networkSentMb": round(self.system.network_sent_mb, 2),
                "networkRecvMb": round(self.system.network_recv_mb, 2),
                "networkSentRateKbps": round(self.system.network_sent_rate_kbps, 2),
                "networkRecvRateKbps": round(self.system.network_recv_rate_kbps, 2),
            },
            "threadPool": {
                "activeThreads": self.thread_pool.active_threads,
                "maxWorkers": self.thread_pool.max_workers,
                "pendingTasks": self.thread_pool.pending_tasks,
                "utilizationPercent": round(self.thread_pool.utilization_percent, 1),
            },
            "usage": {
                "requestsLastHour": self.usage.requests_last_hour,
                "requestsToday": self.usage.requests_today,
                "peakHour": self.usage.peak_hour,
                "peakHourRequests": self.usage.peak_hour_requests,
                "hourlyDistribution": self.usage.hourly_distribution,
            },
            "mcp": {
                "totalServers": self.mcp.total_servers,
                "connectedServers": self.mcp.connected_servers,
                "totalTools": self.mcp.total_tools,
                "totalCalls": self.mcp.total_calls,
                "servers": [
                    {
                        "name": s.name,
                        "status": s.status,
                        "toolCount": s.tool_count,
                        "transport": s.transport,
                        "actionSet": s.action_set,
                        "tools": s.tools[:5],
                    }
                    for s in self.mcp.servers
                ],
                "topTools": [
                    {"name": t.name, "count": t.count}
                    for t in self.mcp.top_tools
                ],
            },
            "skill": {
                "totalSkills": self.skill.total_skills,
                "enabledSkills": self.skill.enabled_skills,
                "totalInvocations": self.skill.total_invocations,
                "skills": [
                    {
                        "name": s.name,
                        "enabled": s.enabled,
                        "description": s.description,
                        "userInvocable": s.user_invocable,
                        "actionSets": s.action_sets,
                    }
                    for s in self.skill.skills
                ],
                "topSkills": [
                    {"name": s.name, "count": s.count}
                    for s in self.skill.top_skills
                ],
            },
            "model": {
                "provider": self.model.provider,
                "modelId": self.model.model_id,
                "modelName": self.model.model_name,
            },
        }


@dataclass
class FilteredDashboardMetrics:
    """Filtered dashboard metrics for a specific time period."""
    period: str  # "1h", "1d", "1w", "1m", "total"
    token: TokenMetrics = field(default_factory=TokenMetrics)
    task: TaskMetrics = field(default_factory=TaskMetrics)
    usage: UsageMetrics = field(default_factory=UsageMetrics)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "period": self.period,
            "token": {
                "input": self.token.total_input_tokens,
                "output": self.token.total_output_tokens,
                "cached": self.token.total_cached_tokens,
                "total": self.token.total_tokens,
            },
            "task": {
                "total": self.task.total_tasks,
                "completed": self.task.completed_tasks,
                "failed": self.task.failed_tasks,
                "running": self.task.running_tasks,
                "successRate": round(self.task.success_rate, 1),
            },
            "usage": {
                "requestsLastHour": self.usage.requests_last_hour,
                "requestsToday": self.usage.requests_today,
                "peakHour": self.usage.peak_hour,
                "peakHourRequests": self.usage.peak_hour_requests,
                "hourlyDistribution": self.usage.hourly_distribution,
            },
        }


# ─────────────────────────────────────────────────────────────────────
# Metrics Collector
# ─────────────────────────────────────────────────────────────────────

class MetricsCollector:
    """
    Collects and aggregates metrics for the dashboard.

    Tracks:
    - LLM call costs and token usage
    - Task success/failure rates
    - System resource usage (CPU, memory, disk, network)
    - Thread pool utilization
    - Request volume and peak usage times
    """

    def __init__(self, agent: Optional["AgentBase"] = None) -> None:
        self._agent = agent
        self._lock = threading.Lock()

        # Startup time
        self._start_time = time.time()

        # LLM call tracking
        self._llm_calls: List[LLMCallRecord] = []
        self._current_task_calls: Dict[str, List[LLMCallRecord]] = defaultdict(list)

        # Task tracking
        self._task_records: List[TaskRecord] = []
        self._running_tasks: Dict[str, float] = {}  # task_id -> start_time
        self._running_task_names: Dict[str, str] = {}  # task_id -> task_name

        # Token totals
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cached_tokens = 0

        # Network tracking for rate calculation
        self._last_network_check: Optional[Tuple[float, float, float]] = None

        # Hourly request tracking
        self._hourly_requests: List[int] = [0] * 24
        self._current_hour = datetime.now().hour

        # MCP tool usage tracking
        self._mcp_tool_usage: Dict[str, int] = defaultdict(int)
        self._mcp_total_calls: int = 0

        # Skill usage tracking
        self._skill_usage: Dict[str, int] = defaultdict(int)
        self._skill_total_invocations: int = 0

        # Storage references for historical data
        self._usage_storage = None
        self._task_storage = None
        self._init_storage()

    def _init_storage(self) -> None:
        """Initialize storage references for historical data."""
        try:
            from app.usage.storage import get_usage_storage
            from app.usage.task_storage import get_task_storage
            self._usage_storage = get_usage_storage()
            self._task_storage = get_task_storage()
        except Exception:
            # Storage may not be available in all contexts
            pass

    def _get_period_bounds(self, period: TimePeriod) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Calculate start/end datetime for the given period."""
        # Use local time to match how tasks are stored (via datetime.fromtimestamp)
        now = datetime.now()
        end_date = now

        if period == TimePeriod.HOUR_1:
            start_date = now - timedelta(hours=1)
        elif period == TimePeriod.DAY_1:
            start_date = now - timedelta(days=1)
        elif period == TimePeriod.WEEK_1:
            start_date = now - timedelta(weeks=1)
        elif period == TimePeriod.MONTH_1:
            start_date = now - timedelta(days=30)
        elif period == TimePeriod.TOTAL:
            return None, None  # No bounds for total
        else:
            return None, None

        return start_date, end_date

    # ─────────────────────────────────────────────────────────────────────
    # LLM Call Tracking
    # ─────────────────────────────────────────────────────────────────────

    def record_llm_call(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        task_id: Optional[str] = None,
    ) -> None:
        """Record an LLM call for cost tracking."""
        pricing = get_model_pricing(model)

        # Calculate cost (per million tokens)
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        # Cached tokens are typically free or heavily discounted
        total_cost = input_cost + output_cost

        record = LLMCallRecord(
            timestamp=time.time(),
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_usd=total_cost,
            task_id=task_id,
        )

        with self._lock:
            self._llm_calls.append(record)
            self._total_input_tokens += input_tokens
            self._total_output_tokens += output_tokens
            self._total_cached_tokens += cached_tokens

            if task_id:
                self._current_task_calls[task_id].append(record)

            # Update hourly tracking
            current_hour = datetime.now().hour
            if current_hour != self._current_hour:
                self._current_hour = current_hour
            self._hourly_requests[current_hour] += 1

        # Persist to UsageStorage (outside lock to avoid blocking)
        if self._usage_storage:
            try:
                from app.usage.storage import UsageEvent
                usage_event = UsageEvent(
                    service_type="llm",
                    provider=provider,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                )
                self._usage_storage.insert_event(usage_event)
            except Exception:
                # Don't fail LLM tracking if storage fails
                pass

    # ─────────────────────────────────────────────────────────────────────
    # Task Tracking
    # ─────────────────────────────────────────────────────────────────────

    def record_task_start(self, task_id: str, name: str) -> None:
        """Record when a task starts."""
        with self._lock:
            self._running_tasks[task_id] = time.time()
            self._running_task_names[task_id] = name

    def record_task_end(self, task_id: str, name: str, status: str) -> None:
        """Record when a task ends."""
        with self._lock:
            start_time = self._running_tasks.pop(task_id, time.time())
            self._running_task_names.pop(task_id, None)
            end_time = time.time()

            # Calculate total cost for this task
            task_calls = self._current_task_calls.pop(task_id, [])
            total_cost = sum(call.cost_usd for call in task_calls)

            record = TaskRecord(
                task_id=task_id,
                name=name,
                status=status,
                start_time=start_time,
                end_time=end_time,
                total_cost=total_cost,
                llm_call_count=len(task_calls),
            )
            self._task_records.append(record)

        # Persist to TaskStorage (outside lock to avoid blocking)
        if self._task_storage:
            try:
                from app.usage.task_storage import TaskEvent
                task_event = TaskEvent(
                    task_id=task_id,
                    task_name=name,
                    status=status,
                    start_time=datetime.fromtimestamp(start_time),
                    end_time=datetime.fromtimestamp(end_time),
                    total_cost=total_cost,
                    llm_call_count=len(task_calls),
                )
                self._task_storage.insert_task(task_event)
            except Exception:
                # Don't fail task tracking if storage fails
                pass

    # ─────────────────────────────────────────────────────────────────────
    # MCP Tool Usage Tracking
    # ─────────────────────────────────────────────────────────────────────

    def record_mcp_tool_call(self, tool_name: str, server_name: str = "") -> None:
        """Record an MCP tool call."""
        with self._lock:
            # Track by tool name (optionally include server)
            key = f"{server_name}:{tool_name}" if server_name else tool_name
            self._mcp_tool_usage[key] += 1
            self._mcp_total_calls += 1

    def get_top_mcp_tools(self, limit: int = 3) -> List[Tuple[str, int]]:
        """Get top N most used MCP tools."""
        with self._lock:
            sorted_tools = sorted(
                self._mcp_tool_usage.items(),
                key=lambda x: x[1],
                reverse=True
            )
            return sorted_tools[:limit]

    # ─────────────────────────────────────────────────────────────────────
    # Skill Usage Tracking
    # ─────────────────────────────────────────────────────────────────────

    def record_skill_invocation(self, skill_name: str) -> None:
        """Record a skill invocation."""
        with self._lock:
            self._skill_usage[skill_name] += 1
            self._skill_total_invocations += 1

    def get_top_skills(self, limit: int = 3) -> List[Tuple[str, int]]:
        """Get top N most used skills."""
        with self._lock:
            sorted_skills = sorted(
                self._skill_usage.items(),
                key=lambda x: x[1],
                reverse=True
            )
            return sorted_skills[:limit]

    # ─────────────────────────────────────────────────────────────────────
    # System Metrics
    # ─────────────────────────────────────────────────────────────────────

    def _get_system_metrics(self) -> SystemMetrics:
        """Get current system resource metrics."""
        if not PSUTIL_AVAILABLE:
            return SystemMetrics()

        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=None)

            # Memory
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_mb = memory.used / (1024 * 1024)
            memory_total_mb = memory.total / (1024 * 1024)

            # Disk
            disk = psutil.disk_usage("/")
            disk_percent = disk.percent
            disk_used_gb = disk.used / (1024 * 1024 * 1024)
            disk_total_gb = disk.total / (1024 * 1024 * 1024)

            # Network
            net_io = psutil.net_io_counters()
            network_sent_mb = net_io.bytes_sent / (1024 * 1024)
            network_recv_mb = net_io.bytes_recv / (1024 * 1024)

            # Calculate network rate
            now = time.time()
            sent_rate = 0.0
            recv_rate = 0.0

            if self._last_network_check:
                last_time, last_sent, last_recv = self._last_network_check
                elapsed = now - last_time
                if elapsed > 0:
                    sent_rate = ((network_sent_mb - last_sent) * 1024) / elapsed  # KB/s
                    recv_rate = ((network_recv_mb - last_recv) * 1024) / elapsed

            self._last_network_check = (now, network_sent_mb, network_recv_mb)

            return SystemMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=memory_used_mb,
                memory_total_mb=memory_total_mb,
                disk_percent=disk_percent,
                disk_used_gb=disk_used_gb,
                disk_total_gb=disk_total_gb,
                network_sent_mb=network_sent_mb,
                network_recv_mb=network_recv_mb,
                network_sent_rate_kbps=sent_rate,
                network_recv_rate_kbps=recv_rate,
            )
        except Exception:
            return SystemMetrics()

    def _get_thread_pool_metrics(self) -> ThreadPoolMetrics:
        """Get thread pool utilization metrics."""
        try:
            # Try to import and check the executor from action executor
            from agent_core.core.impl.action.executor import THREAD_POOL

            # ThreadPoolExecutor doesn't expose pending tasks directly
            # We can check _work_queue size
            pending = 0
            if hasattr(THREAD_POOL, "_work_queue"):
                pending = THREAD_POOL._work_queue.qsize()

            max_workers = THREAD_POOL._max_workers

            # Estimate active threads
            active = threading.active_count()
            utilization = (active / max_workers) * 100 if max_workers > 0 else 0

            return ThreadPoolMetrics(
                active_threads=active,
                max_workers=max_workers,
                pending_tasks=pending,
                utilization_percent=min(utilization, 100),
            )
        except Exception:
            return ThreadPoolMetrics(
                active_threads=threading.active_count(),
                max_workers=16,
            )

    # ─────────────────────────────────────────────────────────────────────
    # MCP and Skill Metrics
    # ─────────────────────────────────────────────────────────────────────

    def _get_mcp_metrics(self) -> MCPMetrics:
        """Get MCP server metrics."""
        try:
            from app.mcp import mcp_client

            servers = []
            total_tools = 0
            connected = 0

            for name, connection in mcp_client.servers.items():
                status = "connected" if connection.is_connected else "disconnected"
                tools = [t.name for t in connection.tools] if connection.tools else []
                tool_count = len(tools)
                total_tools += tool_count

                if connection.is_connected:
                    connected += 1

                # Get transport type and action set from config
                transport = connection.config.transport if connection.config else "stdio"
                action_set = connection.config.resolved_action_set_name if connection.config else ""

                servers.append(MCPServerInfo(
                    name=name,
                    status=status,
                    tool_count=tool_count,
                    transport=transport,
                    action_set=action_set,
                    tools=tools,
                ))

            # Get top tools usage
            top_tools = [
                UsageCount(name=name, count=count)
                for name, count in self.get_top_mcp_tools(3)
            ]

            return MCPMetrics(
                total_servers=len(servers),
                connected_servers=connected,
                total_tools=total_tools,
                total_calls=self._mcp_total_calls,
                servers=servers,
                top_tools=top_tools,
            )
        except Exception:
            return MCPMetrics()

    def _get_skill_metrics(self) -> SkillMetrics:
        """Get skill metrics."""
        try:
            from app.skill import skill_manager

            skills = []
            enabled_count = 0
            user_invocable_count = 0

            status = skill_manager.get_status()
            skill_data_dict = status.get("skills", {})

            for name, skill_data in skill_data_dict.items():
                enabled = skill_data.get("enabled", False)
                description = skill_data.get("description", "")
                user_invocable = skill_data.get("user_invocable", True)
                action_sets = skill_data.get("action_sets", [])

                if enabled:
                    enabled_count += 1
                if user_invocable:
                    user_invocable_count += 1

                skills.append(SkillInfo(
                    name=name,
                    enabled=enabled,
                    description=description,
                    user_invocable=user_invocable,
                    action_sets=action_sets,
                ))

            # Get top skills usage
            top_skills = [
                UsageCount(name=name, count=count)
                for name, count in self.get_top_skills(3)
            ]

            return SkillMetrics(
                total_skills=len(skills),
                enabled_skills=enabled_count,
                total_invocations=self._skill_total_invocations,
                skills=skills,
                top_skills=top_skills,
            )
        except Exception:
            return SkillMetrics()

    # ─────────────────────────────────────────────────────────────────────
    # Model Metrics
    # ─────────────────────────────────────────────────────────────────────

    def _get_model_metrics(self) -> ModelMetrics:
        """Get current model information."""
        try:
            # Try to get from agent's LLM interface first
            if self._agent and hasattr(self._agent, "llm"):
                llm = self._agent.llm
                provider = getattr(llm, "provider", "")
                model_id = getattr(llm, "model", "")

                # Generate friendly name from model ID
                model_name = self._get_friendly_model_name(model_id)

                return ModelMetrics(
                    provider=provider,
                    model_id=model_id,
                    model_name=model_name,
                )

            # Fallback: get from last LLM call
            with self._lock:
                if self._llm_calls:
                    last_call = self._llm_calls[-1]
                    return ModelMetrics(
                        provider=last_call.provider,
                        model_id=last_call.model,
                        model_name=self._get_friendly_model_name(last_call.model),
                    )

            return ModelMetrics()
        except Exception:
            return ModelMetrics()

    def _get_friendly_model_name(self, model_id: str) -> str:
        """Get a friendly display name for a model ID."""
        # Map common model IDs to friendly names
        model_names = {
            "gpt-4o": "GPT-4o",
            "gpt-4o-mini": "GPT-4o Mini",
            "gpt-4-turbo": "GPT-4 Turbo",
            "gpt-4": "GPT-4",
            "gpt-3.5-turbo": "GPT-3.5 Turbo",
            "o1": "o1",
            "o1-mini": "o1 Mini",
            "o1-preview": "o1 Preview",
            "o3-mini": "o3 Mini",
            "claude-3-5-sonnet": "Claude 3.5 Sonnet",
            "claude-3-5-haiku": "Claude 3.5 Haiku",
            "claude-3-opus": "Claude 3 Opus",
            "claude-3-sonnet": "Claude 3 Sonnet",
            "claude-3-haiku": "Claude 3 Haiku",
            "gemini-1.5-pro": "Gemini 1.5 Pro",
            "gemini-1.5-flash": "Gemini 1.5 Flash",
            "gemini-2.0-flash": "Gemini 2.0 Flash",
        }

        model_lower = model_id.lower()
        for key, name in model_names.items():
            if key in model_lower:
                return name

        # Return the model ID as-is if no friendly name found
        return model_id

    # ─────────────────────────────────────────────────────────────────────
    # Metrics Aggregation
    # ─────────────────────────────────────────────────────────────────────

    def get_metrics(self) -> DashboardMetrics:
        """Get the current dashboard metrics snapshot."""
        now = time.time()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)

        today_ts = today_start.timestamp()
        week_ts = week_start.timestamp()
        month_ts = month_start.timestamp()
        hour_ago = now - 3600

        with self._lock:
            # Cost metrics
            total_cost = sum(call.cost_usd for call in self._llm_calls)
            cost_today = sum(
                call.cost_usd for call in self._llm_calls
                if call.timestamp >= today_ts
            )
            cost_week = sum(
                call.cost_usd for call in self._llm_calls
                if call.timestamp >= week_ts
            )
            cost_month = sum(
                call.cost_usd for call in self._llm_calls
                if call.timestamp >= month_ts
            )

            num_calls = len(self._llm_calls)
            avg_cost_per_request = total_cost / num_calls if num_calls > 0 else 0

            # Task cost average
            completed_tasks = [t for t in self._task_records if t.status == "completed"]
            avg_cost_per_task = (
                sum(t.total_cost for t in completed_tasks) / len(completed_tasks)
                if completed_tasks else 0
            )

            # Task metrics
            total_tasks = len(self._task_records)
            completed_count = len([t for t in self._task_records if t.status == "completed"])
            failed_count = len([t for t in self._task_records if t.status == "error"])
            running_count = len(self._running_tasks)

            finished_tasks = completed_count + failed_count
            success_rate = (
                (completed_count / finished_tasks) * 100
                if finished_tasks > 0 else 100.0
            )

            # Usage metrics
            requests_last_hour = len([
                call for call in self._llm_calls
                if call.timestamp >= hour_ago
            ])
            requests_today = len([
                call for call in self._llm_calls
                if call.timestamp >= today_ts
            ])

            # Find peak hour
            peak_hour = 0
            peak_requests = 0
            for hour, count in enumerate(self._hourly_requests):
                if count > peak_requests:
                    peak_requests = count
                    peak_hour = hour

        # Get system metrics (outside lock to avoid blocking)
        system_metrics = self._get_system_metrics()
        thread_pool_metrics = self._get_thread_pool_metrics()
        mcp_metrics = self._get_mcp_metrics()
        skill_metrics = self._get_skill_metrics()
        model_metrics = self._get_model_metrics()

        return DashboardMetrics(
            uptime_seconds=now - self._start_time,
            timestamp=now,
            cost=CostMetrics(
                cost_per_request_avg=avg_cost_per_request,
                cost_per_task_avg=avg_cost_per_task,
                cost_today=cost_today,
                cost_this_week=cost_week,
                cost_this_month=cost_month,
                total_cost=total_cost,
            ),
            task=TaskMetrics(
                total_tasks=total_tasks,
                completed_tasks=completed_count,
                failed_tasks=failed_count,
                running_tasks=running_count,
                success_rate=success_rate,
            ),
            token=TokenMetrics(
                total_input_tokens=self._total_input_tokens,
                total_output_tokens=self._total_output_tokens,
                total_cached_tokens=self._total_cached_tokens,
                total_tokens=self._total_input_tokens + self._total_output_tokens,
            ),
            system=system_metrics,
            thread_pool=thread_pool_metrics,
            usage=UsageMetrics(
                requests_last_hour=requests_last_hour,
                requests_today=requests_today,
                peak_hour=peak_hour,
                peak_hour_requests=peak_requests,
                hourly_distribution=self._hourly_requests.copy(),
            ),
            mcp=mcp_metrics,
            skill=skill_metrics,
            model=model_metrics,
        )

    def get_filtered_metrics(self, period: TimePeriod) -> FilteredDashboardMetrics:
        """
        Get metrics filtered by time period.

        Combines historical data from SQLite storage with in-memory session data.

        Args:
            period: The time period to filter by.

        Returns:
            FilteredDashboardMetrics with token, task, and usage data.
        """
        start_date, end_date = self._get_period_bounds(period)

        # Initialize with defaults
        token_metrics = TokenMetrics()
        task_metrics = TaskMetrics()
        usage_metrics = UsageMetrics()

        # Query historical token/usage data from UsageStorage
        if self._usage_storage:
            try:
                usage_summary = self._usage_storage.get_usage_summary(start_date, end_date)
                token_metrics = TokenMetrics(
                    total_input_tokens=usage_summary.get("total_input_tokens", 0),
                    total_output_tokens=usage_summary.get("total_output_tokens", 0),
                    total_cached_tokens=usage_summary.get("total_cached_tokens", 0),
                    total_tokens=usage_summary.get("total_tokens", 0),
                )

                # Get hourly distribution
                hourly_dist = self._usage_storage.get_hourly_distribution(start_date, end_date)

                # Calculate peak hour
                peak_hour = 0
                peak_requests = 0
                for hour, count in enumerate(hourly_dist):
                    if count > peak_requests:
                        peak_requests = count
                        peak_hour = hour

                # Calculate requests in different periods
                total_calls = usage_summary.get("total_calls", 0)

                usage_metrics = UsageMetrics(
                    requests_last_hour=total_calls if period == TimePeriod.HOUR_1 else 0,
                    requests_today=total_calls if period in (TimePeriod.HOUR_1, TimePeriod.DAY_1) else 0,
                    peak_hour=peak_hour,
                    peak_hour_requests=peak_requests,
                    hourly_distribution=hourly_dist,
                )
            except Exception:
                pass

        # Query historical task data from TaskStorage
        if self._task_storage:
            try:
                task_summary = self._task_storage.get_task_summary(start_date, end_date)
                # Running tasks always come from in-memory (current session)
                with self._lock:
                    running_count = len(self._running_tasks)

                task_metrics = TaskMetrics(
                    total_tasks=task_summary.get("total_tasks", 0) + running_count,
                    completed_tasks=task_summary.get("completed_tasks", 0),
                    failed_tasks=task_summary.get("failed_tasks", 0),
                    running_tasks=running_count,
                    success_rate=task_summary.get("success_rate", 100.0),
                )
            except Exception:
                pass

        return FilteredDashboardMetrics(
            period=period.value,
            token=token_metrics,
            task=task_metrics,
            usage=usage_metrics,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Integration Hook
    # ─────────────────────────────────────────────────────────────────────

    def create_usage_hook(self) -> Callable:
        """Create a usage reporting hook for the LLM interface."""
        async def report_usage(event) -> None:
            """Hook to receive usage events from LLM interface."""
            self.record_llm_call(
                provider=event.provider,
                model=event.model,
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                cached_tokens=event.cached_tokens,
                task_id=None,  # Could be enhanced to track current task
            )
        return report_usage
