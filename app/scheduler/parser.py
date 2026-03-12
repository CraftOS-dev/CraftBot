# -*- coding: utf-8 -*-
"""
Schedule Expression Parser

Parses human-readable schedule expressions and cron expressions.

Supported formats (recurring):
- "every day at 7am"
- "every day at 3:30pm"
- "every monday at 9am"
- "every 3 hours"
- "every 30 minutes"
- "0 7 * * *" (cron expression)

Supported formats (one-time):
- "at 3pm" or "at 3:30pm today"
- "tomorrow at 9am"
- "in 2 hours" or "in 30 minutes"
"""

import re
from datetime import datetime, timedelta
from typing import Optional

from croniter import croniter

from .types import ScheduleExpression


# Weekday name to number mapping (Monday = 0)
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class ScheduleParseError(Exception):
    """Raised when a schedule expression cannot be parsed."""
    pass


class ScheduleParser:
    """
    Parser for schedule expressions.

    Supports both human-readable expressions and cron syntax.
    """

    # Pattern for "every day at TIME"
    DAILY_PATTERN = re.compile(
        r"^every\s+day\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$",
        re.IGNORECASE
    )

    # Pattern for "every WEEKDAY at TIME"
    WEEKLY_PATTERN = re.compile(
        r"^every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$",
        re.IGNORECASE
    )

    # Pattern for "every N hours"
    HOURLY_PATTERN = re.compile(
        r"^every\s+(\d+)\s+hours?$",
        re.IGNORECASE
    )

    # Pattern for "every N minutes"
    MINUTE_PATTERN = re.compile(
        r"^every\s+(\d+)\s+minutes?$",
        re.IGNORECASE
    )

    # Pattern for "every N seconds" (useful for testing)
    SECOND_PATTERN = re.compile(
        r"^every\s+(\d+)\s+seconds?$",
        re.IGNORECASE
    )

    # Pattern for cron expression (5 fields: minute hour day month weekday)
    CRON_PATTERN = re.compile(
        r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$"
    )

    # One-time patterns
    # Pattern for "at TIME" or "at TIME today"
    AT_TIME_PATTERN = re.compile(
        r"^at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s+today)?$",
        re.IGNORECASE
    )

    # Pattern for "tomorrow at TIME"
    TOMORROW_PATTERN = re.compile(
        r"^tomorrow\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$",
        re.IGNORECASE
    )

    # Pattern for "in N hours"
    IN_HOURS_PATTERN = re.compile(
        r"^in\s+(\d+)\s+hours?$",
        re.IGNORECASE
    )

    # Pattern for "in N minutes"
    IN_MINUTES_PATTERN = re.compile(
        r"^in\s+(\d+)\s+minutes?$",
        re.IGNORECASE
    )

    @classmethod
    def parse(cls, expression: str) -> ScheduleExpression:
        """
        Parse a schedule expression.

        Args:
            expression: Human-readable or cron expression

        Returns:
            ScheduleExpression object

        Raises:
            ScheduleParseError: If the expression cannot be parsed
        """
        expression = expression.strip()

        # Try recurring patterns first
        result = cls._parse_daily(expression)
        if result:
            return result

        result = cls._parse_weekly(expression)
        if result:
            return result

        result = cls._parse_interval(expression)
        if result:
            return result

        # Try cron expression
        result = cls._parse_cron(expression)
        if result:
            return result

        # Try one-time patterns
        result = cls._parse_once(expression)
        if result:
            return result

        raise ScheduleParseError(
            f"Cannot parse schedule expression: '{expression}'. "
            f"Expected formats: 'every day at 7am', 'every monday at 9am', "
            f"'every 3 hours', 'every 30 minutes', 'at 3pm', 'tomorrow at 9am', "
            f"'in 2 hours', or cron expression like '0 7 * * *'"
        )

    @classmethod
    def _parse_daily(cls, expression: str) -> Optional[ScheduleExpression]:
        """Parse 'every day at TIME' expressions."""
        match = cls.DAILY_PATTERN.match(expression)
        if not match:
            return None

        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        ampm = match.group(3)

        hour = cls._convert_to_24h(hour, ampm)

        return ScheduleExpression(
            schedule_type="daily",
            raw_expression=expression,
            hour=hour,
            minute=minute,
        )

    @classmethod
    def _parse_weekly(cls, expression: str) -> Optional[ScheduleExpression]:
        """Parse 'every WEEKDAY at TIME' expressions."""
        match = cls.WEEKLY_PATTERN.match(expression)
        if not match:
            return None

        weekday_name = match.group(1).lower()
        hour = int(match.group(2))
        minute = int(match.group(3)) if match.group(3) else 0
        ampm = match.group(4)

        hour = cls._convert_to_24h(hour, ampm)
        weekday = WEEKDAYS[weekday_name]

        return ScheduleExpression(
            schedule_type="weekly",
            raw_expression=expression,
            hour=hour,
            minute=minute,
            weekday=weekday,
        )

    @classmethod
    def _parse_interval(cls, expression: str) -> Optional[ScheduleExpression]:
        """Parse interval expressions (hours, minutes, seconds)."""
        # Try hours
        match = cls.HOURLY_PATTERN.match(expression)
        if match:
            hours = int(match.group(1))
            return ScheduleExpression(
                schedule_type="interval",
                raw_expression=expression,
                interval_seconds=hours * 3600,
            )

        # Try minutes
        match = cls.MINUTE_PATTERN.match(expression)
        if match:
            minutes = int(match.group(1))
            return ScheduleExpression(
                schedule_type="interval",
                raw_expression=expression,
                interval_seconds=minutes * 60,
            )

        # Try seconds
        match = cls.SECOND_PATTERN.match(expression)
        if match:
            seconds = int(match.group(1))
            return ScheduleExpression(
                schedule_type="interval",
                raw_expression=expression,
                interval_seconds=seconds,
            )

        return None

    @classmethod
    def _parse_cron(cls, expression: str) -> Optional[ScheduleExpression]:
        """Parse cron expressions."""
        match = cls.CRON_PATTERN.match(expression)
        if not match:
            return None

        # Validate the cron expression using croniter
        try:
            croniter(expression)
        except (KeyError, ValueError) as e:
            raise ScheduleParseError(f"Invalid cron expression: {expression}. Error: {e}")

        return ScheduleExpression(
            schedule_type="cron",
            raw_expression=expression,
            cron_expression=expression,
        )

    @classmethod
    def _parse_once(cls, expression: str) -> Optional[ScheduleExpression]:
        """Parse one-time schedule expressions."""
        now = datetime.now()

        # Try "at TIME" or "at TIME today"
        match = cls.AT_TIME_PATTERN.match(expression)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            ampm = match.group(3)
            hour = cls._convert_to_24h(hour, ampm)

            scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # If the time has passed today, schedule for tomorrow
            if scheduled <= now:
                scheduled += timedelta(days=1)

            return ScheduleExpression(
                schedule_type="once",
                raw_expression=expression,
                fire_at=scheduled.timestamp(),
            )

        # Try "tomorrow at TIME"
        match = cls.TOMORROW_PATTERN.match(expression)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            ampm = match.group(3)
            hour = cls._convert_to_24h(hour, ampm)

            tomorrow = now + timedelta(days=1)
            scheduled = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)

            return ScheduleExpression(
                schedule_type="once",
                raw_expression=expression,
                fire_at=scheduled.timestamp(),
            )

        # Try "in N hours"
        match = cls.IN_HOURS_PATTERN.match(expression)
        if match:
            hours = int(match.group(1))
            fire_at = now.timestamp() + (hours * 3600)

            return ScheduleExpression(
                schedule_type="once",
                raw_expression=expression,
                fire_at=fire_at,
            )

        # Try "in N minutes"
        match = cls.IN_MINUTES_PATTERN.match(expression)
        if match:
            minutes = int(match.group(1))
            fire_at = now.timestamp() + (minutes * 60)

            return ScheduleExpression(
                schedule_type="once",
                raw_expression=expression,
                fire_at=fire_at,
            )

        return None

    @classmethod
    def _convert_to_24h(cls, hour: int, ampm: Optional[str]) -> int:
        """Convert 12-hour time to 24-hour time."""
        if ampm is None:
            # No AM/PM specified, assume 24-hour format if hour > 12
            return hour
        ampm = ampm.lower()
        if ampm == "am":
            return 0 if hour == 12 else hour
        else:  # pm
            return hour if hour == 12 else hour + 12

    @classmethod
    def calculate_next_fire_time(
        cls,
        schedule: ScheduleExpression,
        from_time: Optional[float] = None
    ) -> float:
        """
        Calculate the next fire time for a schedule.

        Args:
            schedule: The schedule expression
            from_time: Unix timestamp to calculate from (default: now)

        Returns:
            Unix timestamp of next fire time
        """
        if from_time is None:
            from_time = datetime.now().timestamp()

        now = datetime.fromtimestamp(from_time)

        if schedule.schedule_type == "daily":
            return cls._next_daily_fire(now, schedule.hour, schedule.minute)

        elif schedule.schedule_type == "weekly":
            return cls._next_weekly_fire(
                now, schedule.weekday, schedule.hour, schedule.minute
            )

        elif schedule.schedule_type == "interval":
            # For intervals, fire immediately + interval
            return from_time + schedule.interval_seconds

        elif schedule.schedule_type == "cron":
            cron = croniter(schedule.cron_expression, now)
            return cron.get_next(float)

        elif schedule.schedule_type == "once":
            # One-time schedules have a fixed fire_at time
            return schedule.fire_at

        else:
            raise ValueError(f"Unknown schedule type: {schedule.schedule_type}")

    @classmethod
    def _next_daily_fire(
        cls,
        now: datetime,
        hour: int,
        minute: int
    ) -> float:
        """Calculate next fire time for daily schedule."""
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If the scheduled time has passed today, schedule for tomorrow
        if scheduled <= now:
            scheduled += timedelta(days=1)

        return scheduled.timestamp()

    @classmethod
    def _next_weekly_fire(
        cls,
        now: datetime,
        weekday: int,
        hour: int,
        minute: int
    ) -> float:
        """Calculate next fire time for weekly schedule."""
        # Find next occurrence of the weekday
        days_ahead = weekday - now.weekday()
        if days_ahead < 0:  # Target day already happened this week
            days_ahead += 7

        scheduled = now + timedelta(days=days_ahead)
        scheduled = scheduled.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If it's the same day but time has passed, schedule for next week
        if scheduled <= now:
            scheduled += timedelta(weeks=1)

        return scheduled.timestamp()

    @classmethod
    def is_valid_expression(cls, expression: str) -> bool:
        """
        Check if an expression is valid.

        Args:
            expression: Schedule expression to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            cls.parse(expression)
            return True
        except ScheduleParseError:
            return False
