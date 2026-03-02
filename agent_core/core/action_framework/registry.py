# -*- coding: utf-8 -*-
"""
Action framework registry for registering and discovering actions.

The registry uses a singleton pattern to hold all discovered actions
and provides platform-aware action lookup.
"""
import functools
import platform as platform_lib
from typing import List, Dict, Any, Optional, Callable, Union
from dataclasses import dataclass, field
import logging
import inspect
import textwrap
import ast

# Setup basic logging
logger = logging.getLogger("ActionRegistry")

# Standard platform identifiers
PLATFORM_ALL = "all"
PLATFORM_LINUX = "linux"
PLATFORM_WINDOWS = "windows"
PLATFORM_DARWIN = "darwin"  # macOS


def _strip_decorator(source_code: str) -> str:
    """
    Strips the @action decorator and any other decorators from function source code.
    Returns only the function definition and body.
    Supports both sync (def) and async (async def) functions.

    Uses AST parsing which provides exact line numbers for function definitions,
    making this approach robust regardless of decorator complexity.
    """
    try:
        tree = ast.parse(source_code)

        # Find the first function definition (sync or async)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # AST lineno is 1-based, gives the line where 'def' or 'async def' starts
                func_line = node.lineno - 1  # Convert to 0-based index
                lines = source_code.split('\n')
                return '\n'.join(lines[func_line:])

        # No function found, return original
        return source_code
    except SyntaxError as e:
        logger.warning(f"Could not parse source code: {e}")
        return source_code


@dataclass
class ActionMetadata:
    """Holds configuration data defining the action contract."""
    name: str
    description: str = ""
    mode: str = "ALL"
    execution_mode: str = "internal"
    default: bool = False
    # Platforms this specific implementation supports.
    # Defaults to [PLATFORM_ALL] if not specified.
    platforms: List[str] = field(default_factory=lambda: [PLATFORM_ALL])
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    requirements: List[str] = field(default_factory=list)
    test_payload: Optional[Dict[str, Any]] = None
    # Action sets this action belongs to (e.g., ["file_operations", "core"])
    # Used for static action list compilation instead of RAG retrieval
    action_sets: List[str] = field(default_factory=list)
    # Whether this action can be executed in parallel with other actions.
    # Set to False for: write operations, GUI actions, state changes, send_message, etc.
    parallelizable: bool = True

    @property
    def display_name(self) -> str:
        """Returns a user-friendly display name from the snake_case name.

        Examples:
            'grep_files' -> 'Grep files'
            'mouse_click' -> 'Mouse click'
            'web_search' -> 'Web search'
        """
        return self.name.replace('_', ' ').capitalize()


@dataclass
class RegisteredAction:
    """Combines the actual Python callable with its metadata."""
    handler: Callable[..., Dict[str, Any]]
    metadata: ActionMetadata


class ActionRegistry:
    """Singleton registry to hold all discovered actions."""
    _instance = None

    # Storage Structure:
    # {
    #   "logical_action_name": {
    #       "linux": RegisteredAction(...),
    #       "windows": RegisteredAction(...),
    #       "all": RegisteredAction(...)
    #   }
    # }
    _registry: Dict[str, Dict[str, RegisteredAction]] = {}

    def __new__(cls):
        # Ensure singleton pattern
        if cls._instance is None:
            cls._instance = super(ActionRegistry, cls).__new__(cls)
        return cls._instance

    def register(self, action_def: RegisteredAction):
        """Registers an action implementation for its specified platforms."""
        name = action_def.metadata.name

        if name not in self._registry:
            self._registry[name] = {}

        for platform in action_def.metadata.platforms:
            platform_key = platform.lower()

            if platform_key in self._registry[name]:
                logger.warning(f"Overwriting existing action implementation for '{name}' on platform '{platform_key}'")

            self._registry[name][platform_key] = action_def
            logger.debug(f"Registered '{name}' for platform: '{platform_key}'")

    def get_action_implementation(self, name: str, target_platform: Optional[str] = None) -> Optional[RegisteredAction]:
        """
        Retrieves the best fit action implementation.
        1. Looks for exact platform match (e.g., 'linux').
        2. Falls back to generic 'all' match.
        """
        if name not in self._registry:
            return None

        platform_impls = self._registry[name]

        # Detect OS if not provided
        if target_platform is None:
            target_platform = platform_lib.system().lower()
        else:
            target_platform = target_platform.lower()

        # 1. Try specific platform match first
        if target_platform in platform_impls:
            return platform_impls[target_platform]

        # 2. Fallback to generic implementation
        if PLATFORM_ALL in platform_impls:
            return platform_impls[PLATFORM_ALL]

        # 3. No suitable implementation found
        return None

    def get_testable_actions(self, target_platform: Optional[str] = None) -> List[RegisteredAction]:
        """
        Returns a list of unique action implementations that run on the current OS
        AND have valid test_payload data configured for simulation.
        """
        if target_platform is None:
            target_platform = platform_lib.system().lower()

        testable_actions = []

        for logical_name in self._registry.keys():
            # Find the best implementation for this OS
            impl = self.get_action_implementation(logical_name, target_platform)

            # 1. Check if implementation exists and has test payload configured
            if impl and impl.metadata.test_payload is not None:
                payload = impl.metadata.test_payload

                # 2. Inspect the payload. If 'simulated_mode' is explicitly False, skip this test.
                is_simulated = payload.get("simulated_mode", True)

                if is_simulated is False:
                    logger.debug(f"Skipping test for action '{impl.metadata.name}' because simulated_mode is False.")
                    continue

                testable_actions.append(impl)

        return testable_actions

    def list_all_actions(self) -> Dict[str, Any]:
        """Returns the entire registry structure for inspection."""
        return self._registry

    def list_all_actions_as_json(self) -> List[Dict[str, Any]]:
        """
        Returns the registry flattened into JSON-compatible dictionaries matching legacy requirements.
        It extracts the actual source code of the functions using the 'inspect' module.
        """
        json_actions_list = []

        for logical_name, platform_impls in self._registry.items():
            action_json = self._get_action_as_json(platform_impls=platform_impls)
            json_actions_list.append(action_json)

        return json_actions_list

    def find_action_by_name(self, action_name: str) -> Optional[Dict[str, Any]]:
        """Find an action by name and return its JSON representation."""
        if action_name not in self._registry:
            return None

        platform_impls = self._registry[action_name]
        return self._get_action_as_json(platform_impls=platform_impls)

    def _get_action_as_json(self, platform_impls) -> Dict[str, Any]:
        """Convert a platform_impls dict to JSON-compatible dictionary."""
        main_impl = platform_impls.get(platform_lib.system().lower())
        if not main_impl:
            main_impl = platform_impls.get(PLATFORM_ALL)
        if not main_impl:
            main_impl = next(iter(platform_impls.values()))

        meta = main_impl.metadata
        logical_name = meta.name

        # 1. Extract source code for the main implementation
        # Check for stored source code first (used by MCP handlers which are dynamically created)
        if hasattr(main_impl.handler, '_mcp_source_code'):
            main_code_str = main_impl.handler._mcp_source_code
        else:
            try:
                raw_code = inspect.getsource(main_impl.handler)
                dedented_code = textwrap.dedent(raw_code)
                main_code_str = _strip_decorator(dedented_code)
            except Exception as e:
                logger.error(f"Could not extract source for action '{logical_name}': {e}")
                main_code_str = f"# Error extracting source code: {e}"

        # 2. Build the base JSON structure with required hardcoded fields
        action_json = {
            "name": meta.name,
            "description": meta.description,
            "type": "atomic",
            "mode": meta.mode or "CLI",
            "execution_mode": meta.execution_mode or "internal",
            "scope": ["global"],
            "default": meta.default or False,
            "platforms": list(platform_impls.keys()),
            "input_schema": meta.input_schema,
            "output_schema": meta.output_schema,
            "requirements": meta.requirements,
            "code": main_code_str,
            "platform_overrides": {},
            "parallelizable": meta.parallelizable,
        }

        # 3. Handle Platform Overrides
        for platform_key, impl in platform_impls.items():
            if impl == main_impl:
                continue

            if hasattr(impl.handler, '_mcp_source_code'):
                override_code_str = impl.handler._mcp_source_code
            else:
                try:
                    override_raw = inspect.getsource(impl.handler)
                    override_dedented = textwrap.dedent(override_raw)
                    override_code_str = _strip_decorator(override_dedented)
                except Exception as e:
                    logger.warning(f"Could not extract override source for {logical_name} on {platform_key}: {e}")
                    continue

            action_json["platform_overrides"][platform_key] = {
                "code": override_code_str
            }

        # Clean up empty overrides dict if unused
        if not action_json["platform_overrides"]:
            del action_json["platform_overrides"]

        return action_json


# Global singleton instance used by the decorator and the main app
registry_instance = ActionRegistry()


def install_all_action_requirements():
    """
    Collect all unique requirements from registered actions and install them.

    NOTE: This is disabled by default at startup for faster boot times.
    Requirements are installed just-in-time before action execution via
    _ensure_requirements() in executor.py.

    To enable startup installation, set environment variable:
        INSTALL_REQUIREMENTS_AT_STARTUP=true
    """
    import subprocess
    import sys
    from importlib.metadata import distribution, PackageNotFoundError

    # Collect all unique requirements from all registered actions
    all_requirements: set = set()
    for logical_name, platform_impls in registry_instance._registry.items():
        for platform_key, registered_action in platform_impls.items():
            if registered_action.metadata.requirements:
                all_requirements.update(registered_action.metadata.requirements)

    if not all_requirements:
        logger.info("No action requirements to install.")
        return

    logger.info(f"Checking {len(all_requirements)} unique requirements from registered actions...")

    # Check which packages need to be installed
    packages_to_install = []
    for pkg in all_requirements:
        try:
            distribution(pkg)
            logger.debug(f"Package '{pkg}' is already installed.")
        except PackageNotFoundError:
            packages_to_install.append(pkg)

    if not packages_to_install:
        logger.info("All action requirements are already satisfied.")
        return

    logger.info(f"Installing {len(packages_to_install)} missing packages: {packages_to_install}")

    # Install all missing packages in one pip call for efficiency
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet"] + packages_to_install,
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode == 0:
            logger.info(f"Successfully installed packages: {packages_to_install}")
        else:
            logger.warning("Batch install had issues, trying individual installs...")
            for pkg in packages_to_install:
                try:
                    pkg_result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--quiet", pkg],
                        capture_output=True,
                        text=True,
                        timeout=120
                    )
                    if pkg_result.returncode == 0:
                        logger.info(f"Installed: {pkg}")
                    else:
                        stderr_lower = pkg_result.stderr.lower()
                        if "no matching distribution" in stderr_lower or "could not find" in stderr_lower:
                            logger.debug(f"Package '{pkg}' not found on PyPI (may be a class/module name)")
                        else:
                            logger.warning(f"Could not install '{pkg}': {pkg_result.stderr.strip()[:100]}")
                except Exception as e:
                    logger.warning(f"Error installing '{pkg}': {e}")
    except subprocess.TimeoutExpired:
        logger.error("Package installation timed out")
    except Exception as e:
        logger.error(f"Error during package installation: {e}")


# ==========================================
# The Decorator Implementation
# ==========================================
def action(
    name: str,
    description: str = "",
    mode: str = "ALL",
    default: bool = False,
    execution_mode: str = "internal",
    platforms: Union[str, List[str], None] = None,
    input_schema: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Dict[str, Any]] = None,
    requirement: Optional[List[str]] = None,
    test_payload: Optional[Dict[str, Any]] = None,
    action_sets: Optional[List[str]] = None,
    parallelizable: bool = True,
):
    """
    Decorator used by developers to register functions as actions.
    This runs at import time, populating the registry.

    Args:
        name: Unique identifier for the action
        description: Human-readable description of what the action does
        mode: Visibility mode - "CLI", "GUI", or "ALL"
        default: If True, action is always available (legacy, prefer action_sets)
        execution_mode: "internal" or "sandboxed"
        platforms: Target platforms - "linux", "windows", "darwin", or "all"
        input_schema: JSON schema for action parameters
        output_schema: JSON schema for action output
        requirement: List of pip packages required
        test_payload: Test data for simulated execution
        action_sets: List of action set names this action belongs to
                     (e.g., ["file_operations", "core"])
        parallelizable: Whether this action can run in parallel with others.
                        Set to False for write operations, GUI actions, state changes, etc.
    """
    # Normalize platforms input to a list of lowercase strings
    if platforms is None:
        platform_list = [PLATFORM_ALL]
    elif isinstance(platforms, str):
        platform_list = [platforms.lower()]
    else:
        platform_list = [p.lower() for p in platforms]

    def decorator_factory(func: Callable):
        # 1. Create the metadata object from decorator arguments
        metadata = ActionMetadata(
            name=name,
            description=description,
            mode=mode,
            default=default,
            execution_mode=execution_mode,
            platforms=platform_list,
            input_schema=input_schema or {},
            output_schema=output_schema or {},
            requirements=requirement or [],
            test_payload=test_payload,
            action_sets=action_sets or [],
            parallelizable=parallelizable,
        )

        # 2. Create the full registration object
        action_definition = RegisteredAction(
            handler=func,
            metadata=metadata
        )

        # 3. Register immediately with the singleton instance upon import
        registry_instance.register(action_definition)

        # 4. Return the original function unmodified.
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator_factory
