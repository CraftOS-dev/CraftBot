# -*- coding: utf-8 -*-
"""
Base component registry for dependency injection.

This module provides a generic ComponentRegistry class that can be used to register
and retrieve component instances. It follows the same pattern as StateRegistry
but is generic to support any component type.

Usage:
    # Define a registry for a specific component type:
    class TaskManagerRegistry(ComponentRegistry["TaskManagerProtocol"]):
        pass

    # At application startup:
    TaskManagerRegistry.register(lambda: task_manager_instance)

    # In shared code:
    task_manager = TaskManagerRegistry.get()
"""

from typing import Callable, Generic, Optional, TypeVar, TYPE_CHECKING

T = TypeVar("T")


class ComponentRegistry(Generic[T]):
    """
    Generic registry that provides access to component instances.

    Each component type should create a subclass of this registry.
    Projects (CraftBot, CraftBot) register their implementation
    at startup. Shared code then uses get() to access the component
    without knowing the underlying implementation.

    This uses a factory function pattern because:
    - Some components may need dynamic resolution (e.g., per-session instances)
    - Allows lazy initialization
    - Supports testing with mock implementations

    Thread Safety:
        The registry itself is not thread-safe for registration (register() should
        only be called once at startup). The factory function may return different
        instances per thread/session depending on the implementation.

    Example:
        class MyComponentRegistry(ComponentRegistry[MyProtocol]):
            pass

        # At startup:
        MyComponentRegistry.register(lambda: my_instance)

        # In shared code:
        component = MyComponentRegistry.get()
    """

    _provider_factory: Optional[Callable[[], T]] = None

    @classmethod
    def register(cls, factory: Callable[[], T]) -> None:
        """
        Register a factory function that returns the component instance.

        This should be called once at application startup, before any shared
        code attempts to access the component.

        Args:
            factory: Callable that returns the component instance.
        """
        cls._provider_factory = factory

    @classmethod
    def get(cls) -> T:
        """
        Get the component instance.

        This calls the registered factory function to get the current
        component instance.

        Returns:
            The component instance.

        Raises:
            RuntimeError: If no provider has been registered via register().
        """
        if cls._provider_factory is None:
            raise RuntimeError(
                f"{cls.__name__} not initialized. "
                f"Call {cls.__name__}.register() with a factory function at application startup."
            )
        return cls._provider_factory()

    @classmethod
    def get_or_none(cls) -> Optional[T]:
        """
        Get the component instance, or None if not available.

        Unlike get(), this will not raise an error if the registry
        is not initialized or if the factory function fails.

        Returns:
            The component instance, or None if unavailable.
        """
        if cls._provider_factory is None:
            return None
        try:
            return cls._provider_factory()
        except Exception:
            return None

    @classmethod
    def is_registered(cls) -> bool:
        """
        Check if a component provider has been registered.

        Returns:
            True if a provider factory has been registered, False otherwise.
        """
        return cls._provider_factory is not None

    @classmethod
    def clear(cls) -> None:
        """
        Clear the registered provider factory.

        This is primarily useful for testing to reset state between tests.
        """
        cls._provider_factory = None
