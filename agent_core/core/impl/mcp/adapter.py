# -*- coding: utf-8 -*-
"""
MCP Action Adapter Module

Converts MCP tools to actions, enabling seamless integration
of MCP tools with the existing action system.

IMPORTANT: The action system uses exec() on code STRINGS, not direct function calls.
MCP handlers must be generated as string templates with values baked in, and the
source code must be stored for later retrieval by the registry.
"""

from typing import Any, Callable, Dict, List, Tuple

from agent_core.utils.logger import logger
from agent_core.core.action_framework import (
    ActionMetadata,
    PLATFORM_ALL,
    RegisteredAction,
    registry_instance,
)
from agent_core.core.impl.mcp.server import MCPTool


class MCPActionAdapter:
    """
    Converts MCP tools to RegisteredAction objects for the action system.

    The adapter handles:
    - JSON Schema conversion (MCP format -> action input_schema format)
    - Handler creation as string templates (for exec() compatibility)
    - Action registration with the ActionRegistry
    """

    @staticmethod
    def convert_json_schema_to_input_schema(mcp_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert MCP JSON Schema to action input_schema format.

        MCP format (JSON Schema):
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"}
            },
            "required": ["path"]
        }

        Action format:
        {
            "path": {"type": "string", "description": "File path", "required": True}
        }

        Args:
            mcp_schema: MCP tool input schema in JSON Schema format

        Returns:
            Converted input schema for action system
        """
        if not mcp_schema or mcp_schema.get("type") != "object":
            return {}

        properties = mcp_schema.get("properties", {})
        required = set(mcp_schema.get("required", []))

        converted = {}
        for name, prop in properties.items():
            field = {
                "type": prop.get("type", "string"),
            }

            # Add description if present
            if "description" in prop:
                field["description"] = prop["description"]

            # Add example from default if present
            if "default" in prop:
                field["example"] = prop["default"]

            # Mark as required if in required list
            if name in required:
                field["required"] = True

            # Handle enum values
            if "enum" in prop:
                field["enum"] = prop["enum"]

            # Handle nested objects (simplified)
            if prop.get("type") == "object" and "properties" in prop:
                field["type"] = "object"
                field["description"] = prop.get("description", "Nested object")

            # Handle arrays
            if prop.get("type") == "array":
                field["type"] = "array"
                if "items" in prop:
                    field["items"] = prop["items"]

            converted[name] = field

        return converted

    @staticmethod
    def create_mcp_handler_with_source(
        server_name: str, tool_name: str
    ) -> Tuple[Callable, str]:
        """
        Create an MCP handler function AND its source code string.

        The action system uses exec() on code strings, so we generate the handler
        as a string template with server_name and tool_name baked in as literals.
        This ensures the code works correctly when extracted and executed.

        Args:
            server_name: Name of the MCP server
            tool_name: Name of the tool on that server

        Returns:
            Tuple of (handler_function, source_code_string)
        """
        # Generate the source code as a string with values baked in
        # Note: We use double braces {{ }} for dict literals since this is an f-string
        source_code = f'''def mcp_handler(input_data):
    """MCP tool handler for {server_name}/{tool_name}."""
    import asyncio
    from agent_core.core.impl.mcp.client import mcp_client
    from agent_core.utils.logger import logger

    _server = "{server_name}"
    _tool = "{tool_name}"

    # Remove any internal parameters (starting with _)
    tool_args = {{
        k: v for k, v in input_data.items() if not k.startswith("_")
    }}

    async def async_call():
        return await mcp_client.call_tool(_server, _tool, tool_args)

    try:
        # Get the event loop that the MCP client was initialized with
        # This is critical - MCP connections are tied to a specific event loop
        loop = mcp_client.event_loop

        if loop is None:
            return {{"status": "error", "message": "MCP client not initialized"}}

        # Use run_coroutine_threadsafe to schedule on the MCP client's event loop
        # This works from any thread (including ThreadPoolExecutor workers)
        future = asyncio.run_coroutine_threadsafe(async_call(), loop)
        return future.result(timeout=60)
    except Exception as e:
        logger.error(f"Error calling MCP tool {{_server}}/{{_tool}}: {{e}}")
        return {{"status": "error", "message": str(e)}}
'''

        # Create the actual function by executing the source
        local_ns = {}
        exec(source_code, local_ns)
        handler = local_ns['mcp_handler']

        # Store the source code on the function for later retrieval by the registry
        # This is critical - inspect.getsource() won't work on dynamically created functions
        handler._mcp_source_code = source_code

        return handler, source_code

    @staticmethod
    def mcp_tool_to_registered_action(
        server_name: str,
        tool: MCPTool,
        action_set_name: str,
        server_description: str = "",
    ) -> RegisteredAction:
        """
        Convert an MCP tool to a RegisteredAction.

        Args:
            server_name: Name of the MCP server
            tool: MCPTool object to convert
            action_set_name: Name of the action set to assign
            server_description: Optional server description for context

        Returns:
            RegisteredAction ready for registration
        """
        # Generate unique action name
        action_name = f"mcp_{server_name}_{tool.name}"

        # Build description with MCP context
        description_parts = [f"[MCP:{server_name}]"]
        if tool.description:
            description_parts.append(tool.description)
        elif server_description:
            description_parts.append(f"{tool.name} from {server_description}")
        else:
            description_parts.append(f"MCP tool: {tool.name}")
        description = " ".join(description_parts)

        # Convert input schema
        input_schema = MCPActionAdapter.convert_json_schema_to_input_schema(
            tool.input_schema
        )

        # Create handler with source code (for exec() compatibility)
        handler, source_code = MCPActionAdapter.create_mcp_handler_with_source(
            server_name, tool.name
        )

        # Build metadata
        metadata = ActionMetadata(
            name=action_name,
            description=description,
            mode="CLI",
            execution_mode="internal",  # Runs in-process via exec()
            default=False,
            platforms=[PLATFORM_ALL],
            input_schema=input_schema,
            output_schema={
                "status": {"type": "string", "description": "Execution status (success/error)"},
                "result": {"type": "any", "description": "Tool execution result"},
                "message": {"type": "string", "description": "Error message if failed"},
            },
            requirements=[],  # MCP tools don't have Python requirements
            test_payload=None,  # No test payload for MCP tools
            action_sets=[action_set_name],
        )

        return RegisteredAction(handler=handler, metadata=metadata)

    @staticmethod
    def register_mcp_tools(
        server_name: str,
        tools: List[MCPTool],
        action_set_name: str,
        server_description: str = "",
    ) -> int:
        """
        Register all tools from an MCP server as actions.

        Args:
            server_name: Name of the MCP server
            tools: List of MCPTool objects to register
            action_set_name: Name of the action set to assign
            server_description: Optional server description for context

        Returns:
            Number of tools successfully registered
        """
        count = 0

        for tool in tools:
            try:
                action = MCPActionAdapter.mcp_tool_to_registered_action(
                    server_name=server_name,
                    tool=tool,
                    action_set_name=action_set_name,
                    server_description=server_description,
                )

                # Register with the singleton registry
                registry_instance.register(action)
                count += 1

                logger.debug(
                    f"Registered MCP tool as action: {action.metadata.name}"
                )

            except Exception as e:
                logger.error(
                    f"Failed to register MCP tool '{tool.name}' from "
                    f"server '{server_name}': {e}"
                )

        return count

    @staticmethod
    def unregister_mcp_tools(server_name: str) -> int:
        """
        Unregister all MCP tools from a specific server.

        Note: The ActionRegistry doesn't have a built-in unregister method,
        so this creates a workaround by removing from the internal registry.

        Args:
            server_name: Name of the MCP server

        Returns:
            Number of tools unregistered
        """
        prefix = f"mcp_{server_name}_"
        count = 0

        # Find and remove matching actions
        actions_to_remove = [
            name for name in registry_instance._registry.keys()
            if name.startswith(prefix)
        ]

        for action_name in actions_to_remove:
            del registry_instance._registry[action_name]
            count += 1
            logger.debug(f"Unregistered MCP action: {action_name}")

        return count
