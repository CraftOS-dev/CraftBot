# -*- coding: utf-8 -*-
"""
Observation class for action validation.

Although implemented, this observe is not USED at all yet.
This observe will be fired after action completion, if implemented.
This causes the action to have an immediate validation step followed up.

For example, action that creates a folder path will be followed by an observation step
to make sure the folder path is created successfully. This creates another
layer of validation.
"""

from typing import Optional, Dict, Any


class Observe:
    """
    Defines how to confirm that an action completed successfully in the real world.

    Observation logic is defined as Python code that executes repeatedly until
    success or timeout is reached.

    Attributes:
        name: Identifier for this observation (e.g., "check_file_created")
        description: Human-readable description of what is being observed
        code: Python code to confirm action success
        retry_interval_sec: Seconds between retry attempts (default: 3)
        max_retries: Maximum number of retry attempts (default: 20)
        max_total_time_sec: Maximum total time allowed regardless of retries (default: 60)
        wait_to_observe_sec: Optional delay before first observation or between observations
        input_schema: Schema for observation inputs
        success: Final result of observation (True/False/None)
        message: Optional output message from observation
    """

    def __init__(
        self,
        name: str,
        description: Optional[str] = None,
        code: Optional[str] = None,
        retry_interval_sec: int = 3,
        max_retries: int = 20,
        max_total_time_sec: int = 60,
        wait_to_observe_sec: Optional[int] = None,
        input_schema: Optional[dict] = None,
        success: Optional[bool] = None,
        message: Optional[str] = None,
    ):
        """
        Initialize an Observe instance.

        Args:
            name: Unique identifier for this observation
            description: Human-readable description
            code: Python code to execute for validation
            retry_interval_sec: Seconds between retries (default: 3)
            max_retries: Maximum retry attempts (default: 20)
            max_total_time_sec: Maximum total time in seconds (default: 60)
            wait_to_observe_sec: Optional initial wait time
            input_schema: Dictionary describing expected inputs
            success: Whether observation succeeded (set after execution)
            message: Optional message from observation
        """
        self.name = name
        self.description = description
        self.code = code

        self.retry_interval_sec = retry_interval_sec
        self.max_retries = max_retries
        self.max_total_time_sec = max_total_time_sec
        self.wait_to_observe_sec = wait_to_observe_sec

        self.input_schema = input_schema or {}
        self.success = success
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert Observe to dictionary format for serialization.

        Returns:
            Dictionary representation of the observation
        """
        return {
            "name": self.name,
            "description": self.description,
            "code": self.code,
            "retry_interval_sec": self.retry_interval_sec,
            "max_retries": self.max_retries,
            "max_total_time_sec": self.max_total_time_sec,
            "wait_to_observe_sec": self.wait_to_observe_sec,
            "input_schema": self.input_schema,
            "success": self.success,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Observe":
        """
        Create an Observe instance from a dictionary.

        Args:
            data: Dictionary containing observation data

        Returns:
            Observe instance
        """
        return cls(
            name=data["name"],
            description=data.get("description"),
            code=data.get("code"),
            retry_interval_sec=data.get("retry_interval_sec", 3),
            max_retries=data.get("max_retries", 20),
            max_total_time_sec=data.get("max_total_time_sec", 600),
            wait_to_observe_sec=data.get("wait_to_observe_sec"),
            input_schema=data.get("input_schema") or {},
            success=data.get("success"),
            message=data.get("message"),
        )
