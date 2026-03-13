# Custom Action Development Guide

This guide provides comprehensive instructions for creating custom actions in CraftBot. Actions are the primary way agents execute work and interact with the system.

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start Template](#quick-start-template)
3. [The @action Decorator](#the-action-decorator)
4. [Input and Output Schemas](#input-and-output-schemas)
5. [Execution Modes](#execution-modes)
6. [Action Sets](#action-sets)
7. [Platform-Specific Actions](#platform-specific-actions)
8. [Testing Your Action](#testing-your-action)
9. [Complete Examples](#complete-examples)
10. [Best Practices](#best-practices)
11. [Checklist](#checklist)

---

## Overview

Actions in CraftBot are Python functions decorated with `@action` that define executable operations. When the agent needs to perform a task, it selects and executes appropriate actions based on their descriptions and schemas.

**Key Concepts:**
- **Action**: A single executable operation with defined inputs and outputs
- **Action Set**: A logical grouping of related actions (e.g., "file_operations", "web_research")
- **Execution Mode**: How the action runs ("internal" or "sandboxed")
- **Platform**: Which OS the action supports (windows, linux, darwin)

**File Location:** Place your custom action files in `core/data/action/`

---

## Quick Start Template

Create a new Python file in `core/data/action/` (e.g., `my_custom_action.py`):

```python
from app.action.action_framework.registry import action


@action(
    name="my_custom_action",
    description="Brief description of what this action does",
    mode="ALL",
    execution_mode="internal",
    action_sets=["core"],
    input_schema={
        "param1": {
            "type": "string",
            "example": "example_value",
            "description": "Description of this parameter"
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result status: 'success' or 'error'"
        },
        "result": {
            "type": "string",
            "example": "Operation completed",
            "description": "The result of the operation"
        }
    },
    test_payload={
        "param1": "test_value",
        "simulated_mode": True
    }
)
def my_custom_action(input_data: dict) -> dict:
    """
    Implementation of the custom action.

    Args:
        input_data: Dictionary containing parameters defined in input_schema

    Returns:
        Dictionary with fields defined in output_schema
    """
    # Extract parameters
    param1 = input_data.get("param1", "")
    simulated_mode = input_data.get("simulated_mode", False)

    # Validation
    if not param1:
        return {"status": "error", "message": "param1 is required"}

    # Implementation
    try:
        if simulated_mode:
            return {"status": "success", "result": "Simulated execution"}

        # Your actual logic here
        result = f"Processed: {param1}"

        return {"status": "success", "result": result}

    except Exception as e:
        return {"status": "error", "message": str(e)}
```

---

## The @action Decorator

The `@action` decorator registers your function as an executable action. Here are all available parameters:

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | str | Unique identifier in snake_case (e.g., `"find_files"`) |
| `description` | str | Clear, concise description of what the action does |

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | str | `"ALL"` | Visibility mode: `"CLI"`, `"GUI"`, or `"ALL"` |
| `execution_mode` | str | `"internal"` | `"internal"` (in-process) or `"sandboxed"` (isolated) |
| `default` | bool | `False` | If `True`, action is always available |
| `platforms` | List[str] | `["all"]` | Supported platforms: `"windows"`, `"linux"`, `"darwin"`, `"all"` |
| `input_schema` | dict | `{}` | Parameter definitions (see [Input and Output Schemas](#input-and-output-schemas)) |
| `output_schema` | dict | `{}` | Return value definitions |
| `requirement` | List[str] | `None` | Pip packages required (for sandboxed mode) |
| `test_payload` | dict | `None` | Test data for validation |
| `action_sets` | List[str] | `[]` | Action set membership (see [Action Sets](#action-sets)) |
| `timeout` | int | `6000` | Execution timeout in seconds |

### Import Statement

```python
from app.action.action_framework.registry import action
```

---

## Input and Output Schemas

Schemas define the parameters your action accepts and the values it returns. They help the LLM understand how to use your action correctly.

### Schema Structure

Each field in a schema is defined as:

```python
"field_name": {
    "type": "string",           # Required: data type
    "example": "example_value", # Required: example value
    "description": "..."        # Required: what this field is for
}
```

### Supported Types

| Type | Python Equivalent | Example |
|------|------------------|---------|
| `"string"` | `str` | `"hello world"` |
| `"integer"` | `int` | `42` |
| `"number"` | `float` | `3.14` |
| `"boolean"` | `bool` | `True` |
| `"array"` | `list` | `["item1", "item2"]` |
| `"object"` | `dict` | `{"key": "value"}` |

### Input Schema Example

```python
input_schema={
    "file_path": {
        "type": "string",
        "example": "/path/to/file.txt",
        "description": "Absolute path to the target file"
    },
    "line_count": {
        "type": "integer",
        "example": 10,
        "description": "Number of lines to read (default: all)"
    },
    "recursive": {
        "type": "boolean",
        "example": True,
        "description": "Whether to search subdirectories"
    },
    "keywords": {
        "type": "array",
        "example": ["error", "warning"],
        "description": "List of keywords to search for"
    }
}
```

### Output Schema Example

```python
output_schema={
    "status": {
        "type": "string",
        "example": "success",
        "description": "Result status: 'success' or 'error'"
    },
    "data": {
        "type": "array",
        "example": ["line1", "line2"],
        "description": "Matching lines found"
    },
    "count": {
        "type": "integer",
        "example": 42,
        "description": "Total number of matches"
    },
    "message": {
        "type": "string",
        "example": "Operation completed successfully",
        "description": "Human-readable result message"
    }
}
```

### Standard Output Fields

It's recommended to always include these fields in your output:

```python
output_schema={
    "status": {
        "type": "string",
        "example": "success",
        "description": "Result status: 'success' or 'error'"
    },
    "message": {
        "type": "string",
        "example": "Operation completed",
        "description": "Human-readable result or error message"
    }
}
```

---

## Execution Modes

### Internal Mode (`execution_mode="internal"`)

- Executes in the main process thread pool
- Faster execution
- Can access framework internals via `app.internal_action_interface`
- All dependencies must be pre-installed
- Best for: lightweight operations, framework integration

```python
@action(
    name="send_notification",
    execution_mode="internal",  # Runs in-process
    ...
)
def send_notification(input_data: dict) -> dict:
    import app.internal_action_interface as iai
    # Can access internal framework functions
    ...
```

### Sandboxed Mode (`execution_mode="sandboxed"`)

- Executes in an isolated virtual environment
- Fresh Python interpreter for each execution
- Can specify pip requirements
- More secure but slightly slower
- Best for: untrusted code, heavy dependencies, isolation

```python
@action(
    name="analyze_data",
    execution_mode="sandboxed",  # Runs in isolation
    requirement=["pandas", "numpy"],  # Pip packages to install
    ...
)
def analyze_data(input_data: dict) -> dict:
    import pandas as pd  # Available because of requirement
    import numpy as np
    ...
```

---

## Action Sets

Action sets group related actions together. During task execution, only actions from selected sets are available to the agent.

### Standard Action Sets

| Set Name | Description |
|----------|-------------|
| `"core"` | Essential actions (always included) - messaging, task management |
| `"file_operations"` | File and folder manipulation |
| `"web_research"` | Internet search and browsing |
| `"document_processing"` | PDF and document handling |
| `"gui_interaction"` | Mouse, keyboard, screen operations |
| `"clipboard"` | Clipboard operations |
| `"shell"` | Command line and Python execution |

### Assigning Action Sets

Actions can belong to multiple sets:

```python
@action(
    name="search_and_save",
    action_sets=["web_research", "file_operations"],  # Multiple sets
    ...
)
```

### Creating Custom Sets

Simply use a new set name - it will be discovered automatically:

```python
@action(
    name="my_specialized_action",
    action_sets=["my_custom_set"],  # New custom set
    ...
)
```

---

## Platform-Specific Actions

For actions that behave differently across operating systems, create multiple implementations with the same `name` but different `platforms`:

```python
# Unix implementation (Linux and macOS)
@action(
    name="find_process",
    description="Find a running process by name",
    platforms=["linux", "darwin"],
    action_sets=["shell"],
    input_schema={
        "process_name": {
            "type": "string",
            "example": "python",
            "description": "Name of the process to find"
        }
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "Result status"},
        "pids": {"type": "array", "example": [1234, 5678], "description": "Process IDs found"}
    }
)
def find_process_unix(input_data: dict) -> dict:
    import subprocess
    process_name = input_data.get("process_name", "")

    result = subprocess.run(
        ["pgrep", "-f", process_name],
        capture_output=True, text=True
    )

    pids = [int(pid) for pid in result.stdout.strip().split('\n') if pid]
    return {"status": "success", "pids": pids}


# Windows implementation
@action(
    name="find_process",
    description="Find a running process by name",
    platforms=["windows"],
    action_sets=["shell"],
    input_schema={
        "process_name": {
            "type": "string",
            "example": "python",
            "description": "Name of the process to find"
        }
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "Result status"},
        "pids": {"type": "array", "example": [1234, 5678], "description": "Process IDs found"}
    }
)
def find_process_windows(input_data: dict) -> dict:
    import subprocess
    process_name = input_data.get("process_name", "")

    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {process_name}*"],
        capture_output=True, text=True
    )

    # Parse Windows tasklist output
    pids = []
    for line in result.stdout.split('\n')[3:]:  # Skip header
        parts = line.split()
        if len(parts) >= 2:
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass

    return {"status": "success", "pids": pids}
```

The framework automatically selects the correct implementation based on the current OS.

---

## Testing Your Action

### Test Payload

Include a `test_payload` with your action for simulated testing:

```python
@action(
    name="my_action",
    test_payload={
        "param1": "test_value",
        "param2": 42,
        "simulated_mode": True  # Convention for skipping real operations
    },
    ...
)
def my_action(input_data: dict) -> dict:
    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        # Return mock data for testing
        return {"status": "success", "result": "Simulated result"}

    # Real implementation
    ...
```

### Manual Testing

You can test your action by importing and calling it directly:

```python
from app.data.action.my_custom_action import my_custom_action

# Test with your test payload
result = my_custom_action({
    "param1": "test_value",
    "simulated_mode": True
})

print(result)
# {'status': 'success', 'result': 'Simulated result'}
```

---

## Complete Examples

### Example 1: Simple File Action

```python
from app.action.action_framework.registry import action
import os


@action(
    name="count_lines",
    description="Count the number of lines in a text file",
    mode="ALL",
    execution_mode="internal",
    action_sets=["file_operations"],
    input_schema={
        "file_path": {
            "type": "string",
            "example": "/path/to/file.txt",
            "description": "Absolute path to the file"
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result status: 'success' or 'error'"
        },
        "line_count": {
            "type": "integer",
            "example": 150,
            "description": "Total number of lines in the file"
        },
        "message": {
            "type": "string",
            "example": "File has 150 lines",
            "description": "Human-readable result"
        }
    },
    test_payload={
        "file_path": "/tmp/test.txt",
        "simulated_mode": True
    }
)
def count_lines(input_data: dict) -> dict:
    file_path = input_data.get("file_path", "")
    simulated_mode = input_data.get("simulated_mode", False)

    if not file_path:
        return {"status": "error", "message": "file_path is required"}

    if simulated_mode:
        return {"status": "success", "line_count": 100, "message": "Simulated: 100 lines"}

    if not os.path.exists(file_path):
        return {"status": "error", "message": f"File not found: {file_path}"}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            line_count = sum(1 for _ in f)

        return {
            "status": "success",
            "line_count": line_count,
            "message": f"File has {line_count} lines"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### Example 2: Action with Framework Integration

```python
from app.action.action_framework.registry import action


@action(
    name="notify_user",
    description="Send a notification message to the user through the chat interface",
    mode="ALL",
    execution_mode="internal",
    default=True,
    action_sets=["core"],
    input_schema={
        "title": {
            "type": "string",
            "example": "Task Complete",
            "description": "Notification title"
        },
        "message": {
            "type": "string",
            "example": "Your file has been processed successfully",
            "description": "Notification body text"
        },
        "priority": {
            "type": "string",
            "example": "normal",
            "description": "Priority level: 'low', 'normal', or 'high'"
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result status"
        },
        "notification_id": {
            "type": "string",
            "example": "notif_12345",
            "description": "Unique ID of the sent notification"
        }
    },
    test_payload={
        "title": "Test",
        "message": "Test notification",
        "priority": "normal",
        "simulated_mode": True
    }
)
def notify_user(input_data: dict) -> dict:
    import asyncio
    import uuid

    title = input_data.get("title", "Notification")
    message = input_data.get("message", "")
    priority = input_data.get("priority", "normal")
    simulated_mode = input_data.get("simulated_mode", False)

    if not message:
        return {"status": "error", "message": "message is required"}

    notification_id = f"notif_{uuid.uuid4().hex[:8]}"

    if simulated_mode:
        return {"status": "success", "notification_id": notification_id}

    # Access framework internals for sending messages
    import app.internal_action_interface as iai

    formatted_message = f"**{title}**\n\n{message}"
    asyncio.run(iai.InternalActionInterface.do_chat(formatted_message))

    return {"status": "success", "notification_id": notification_id}
```

### Example 3: Sandboxed Action with Dependencies

```python
from app.action.action_framework.registry import action


@action(
    name="analyze_csv",
    description="Analyze a CSV file and return statistical summary",
    mode="ALL",
    execution_mode="sandboxed",
    requirement=["pandas"],
    action_sets=["document_processing", "file_operations"],
    input_schema={
        "file_path": {
            "type": "string",
            "example": "/data/report.csv",
            "description": "Path to the CSV file"
        },
        "columns": {
            "type": "array",
            "example": ["sales", "revenue"],
            "description": "Columns to analyze (empty for all)"
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result status"
        },
        "row_count": {
            "type": "integer",
            "example": 1000,
            "description": "Number of rows in the file"
        },
        "column_count": {
            "type": "integer",
            "example": 10,
            "description": "Number of columns"
        },
        "summary": {
            "type": "object",
            "example": {"sales": {"mean": 100.5, "min": 10, "max": 500}},
            "description": "Statistical summary per column"
        }
    },
    test_payload={
        "file_path": "/tmp/test.csv",
        "columns": [],
        "simulated_mode": True
    }
)
def analyze_csv(input_data: dict) -> dict:
    import pandas as pd

    file_path = input_data.get("file_path", "")
    columns = input_data.get("columns", [])
    simulated_mode = input_data.get("simulated_mode", False)

    if not file_path:
        return {"status": "error", "message": "file_path is required"}

    if simulated_mode:
        return {
            "status": "success",
            "row_count": 100,
            "column_count": 5,
            "summary": {"col1": {"mean": 50.0, "min": 1, "max": 100}}
        }

    try:
        df = pd.read_csv(file_path)

        if columns:
            df = df[columns]

        summary = {}
        for col in df.select_dtypes(include=['number']).columns:
            summary[col] = {
                "mean": float(df[col].mean()),
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "std": float(df[col].std())
            }

        return {
            "status": "success",
            "row_count": len(df),
            "column_count": len(df.columns),
            "summary": summary
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

---

## Best Practices

### Naming Conventions

- Use `snake_case` for action names: `find_files`, `send_message`
- Use descriptive names that indicate the action's purpose
- Prefix related actions consistently: `file_read`, `file_write`, `file_delete`

### Error Handling

Always return proper error responses:

```python
def my_action(input_data: dict) -> dict:
    try:
        # Validate required parameters
        required_param = input_data.get("required_param")
        if not required_param:
            return {"status": "error", "message": "required_param is required"}

        # Your logic here
        result = do_something(required_param)

        return {"status": "success", "result": result}

    except FileNotFoundError as e:
        return {"status": "error", "message": f"File not found: {e}"}
    except PermissionError as e:
        return {"status": "error", "message": f"Permission denied: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}
```

### Documentation

- Write clear `description` that explains what the action does in one sentence
- Document each parameter in `input_schema` with meaningful descriptions
- Provide realistic `example` values that demonstrate expected format

### Simulated Mode

Always support `simulated_mode` for testing:

```python
simulated_mode = input_data.get("simulated_mode", False)
if simulated_mode:
    return {"status": "success", "result": "Mock result for testing"}
```

### Resource Cleanup

Clean up resources in finally blocks:

```python
def my_action(input_data: dict) -> dict:
    temp_file = None
    try:
        temp_file = create_temp_file()
        # Use temp_file
        return {"status": "success"}
    finally:
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
```

---

## Checklist

Before submitting your custom action, verify:

- [ ] **Unique name** - Action name is unique and follows snake_case convention
- [ ] **Clear description** - Description clearly explains what the action does
- [ ] **Correct action_sets** - Action is assigned to appropriate set(s)
- [ ] **Proper mode** - Visibility mode is set correctly ("CLI", "GUI", or "ALL")
- [ ] **Complete input_schema** - All parameters are documented with type, example, and description
- [ ] **Complete output_schema** - All return fields are documented
- [ ] **Status field** - Output includes a "status" field with "success" or "error"
- [ ] **Error handling** - All errors return proper error responses with messages
- [ ] **Test payload** - `test_payload` is provided for testing
- [ ] **Simulated mode** - Action supports `simulated_mode` for testing
- [ ] **Execution mode** - Correct `execution_mode` is chosen ("internal" or "sandboxed")
- [ ] **Requirements** - Pip packages are listed in `requirement` (for sandboxed mode)
- [ ] **Platform support** - Platform-specific implementations exist if needed
- [ ] **Timeout** - Custom `timeout` is set if operation may take long

---

## File Structure Reference

```
core/
├── action/
│   ├── action.py                    # Action base class
│   ├── action_manager.py            # Execution engine
│   ├── action_library.py            # Storage/retrieval
│   ├── action_router.py             # Selection logic
│   ├── action_set.py                # Set management
│   └── action_framework/
│       ├── registry.py              # @action decorator
│       └── loader.py                # Dynamic discovery
│
├── data/
│   └── action/                      # Place custom actions here
│       ├── send_message.py
│       ├── find_files.py
│       ├── grep_files.py
│       ├── my_custom_action.py      # Your custom action
│       └── CUSTOM_ACTION_GUIDE.md   # This guide
│
└── internal_action_interface.py     # Framework functions for internal mode
```

---

## Need Help?

- Review existing actions in `core/data/action/` for more examples
- Check the action framework code in `core/action/action_framework/registry.py`
- Look at `core/action/action_manager.py` for execution details
