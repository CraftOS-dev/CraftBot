from agent_core import action

@action(
    name="find_files",
    description="Finds files by name or pattern across the system. Supports wildcards and recursive search. Use absolute paths for base_directory.",
    mode="CLI",
    platforms=["linux", "darwin"],
    action_sets=["core"],
    input_schema={
        "pattern": {
            "type": "string",
            "example": "*.pdf",
            "description": "The file name or glob pattern to match. Supports wildcards like * and ?"
        },
        "recursive": {
            "type": "boolean",
            "example": True,
            "description": "Whether to search directories recursively. Default is true."
        },
        "base_directory": {
            "type": "string",
            "example": "/home/user/Documents",
            "description": "Absolute path to the base directory to start searching from. Use full absolute paths (e.g., /home/user/Documents or /Users/name/Desktop)."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success"
        },
        "matches": {
            "type": "array",
            "items": {
                "type": "string"
            },
            "example": [
                "/home/user/Documents/file1.pdf",
                "/home/user/Documents/reports/file2.pdf"
            ]
        },
        "message": {
            "type": "string",
            "example": "No files matched."
        }
    },
    test_payload={
        "pattern": "*.pdf",
        "recursive": True,
        "base_directory": "/home/user/Documents",
        "simulated_mode": True
    }
)
def find_file_by_name(input_data: dict) -> dict:
    import os
    import fnmatch

    pattern = (input_data.get("pattern") or "").strip()
    recursive = bool(input_data.get("recursive", True))
    base_directory = (input_data.get("base_directory") or "").strip()

    if not pattern:
        return {"status": "error", "matches": [], "message": "Pattern is required."}

    # Default to user's home directory if not provided
    if not base_directory:
        base_directory = os.path.expanduser("~")

    # Expand ~ and normalize base directory
    base_directory = os.path.expanduser(base_directory)
    base_directory = os.path.normpath(base_directory)

    if not os.path.exists(base_directory):
        return {
            "status": "error",
            "matches": [],
            "message": f"Base directory does not exist: {base_directory}"
        }

    if not os.path.isdir(base_directory):
        return {
            "status": "error",
            "matches": [],
            "message": f"Base directory is not a directory: {base_directory}"
        }

    # Normalize the pattern (if user passes a path, only use its basename as the match pattern)
    pattern = os.path.expanduser(pattern)
    pattern = os.path.normpath(pattern)
    file_pattern = os.path.basename(pattern) if (os.path.isabs(pattern) or os.sep in pattern) else pattern

    matches = []
    for root, dirs, files in os.walk(base_directory):
        try:
            for name in files:
                if fnmatch.fnmatch(name, file_pattern):
                    matches.append(os.path.abspath(os.path.join(root, name)))
        except PermissionError:
            # Skip directories we don't have access to
            continue

        if not recursive:
            break

    return {
        "status": "success",
        "matches": matches,
        "message": "" if matches else f"No files matching '{file_pattern}' were found in '{base_directory}'."
    }


@action(
    name="find_files",
    description="Finds files by name or pattern across the system. Supports wildcards and recursive search. Use absolute paths for base_directory.",
    mode="CLI",
    platforms=["windows"],
    action_sets=["file_operations"],
    input_schema={
        "pattern": {
            "type": "string",
            "example": "*.pdf",
            "description": "The file name or glob pattern to match. Supports wildcards like * and ?"
        },
        "recursive": {
            "type": "boolean",
            "example": True,
            "description": "Whether to search directories recursively. Default is true."
        },
        "base_directory": {
            "type": "string",
            "example": "C:/Users/user/Documents",
            "description": "Absolute path to the base directory to start searching from. Use full absolute paths (e.g., C:/Users/user/Documents or D:/Projects)."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success"
        },
        "matches": {
            "type": "array",
            "items": {
                "type": "string"
            },
            "example": [
                "C:/Users/user/Documents/file1.pdf",
                "C:/Users/user/Documents/reports/file2.pdf"
            ]
        },
        "message": {
            "type": "string",
            "example": "No files matched."
        }
    },
    test_payload={
        "pattern": "*.pdf",
        "recursive": True,
        "base_directory": "C:/Users/user/Documents",
        "simulated_mode": True
    }
)
def find_file_by_name_windows(input_data: dict) -> dict:
    import os
    import fnmatch

    pattern = (input_data.get("pattern") or "").strip()
    recursive = bool(input_data.get("recursive", True))
    base_directory = (input_data.get("base_directory") or "").strip()

    if not pattern:
        return {"status": "error", "matches": [], "message": "Pattern is required."}

    # Default to user's home directory if not provided
    if not base_directory:
        base_directory = os.path.expanduser("~")

    # Windows-friendly normalization
    base_directory = base_directory.replace("/", "\\")
    base_directory = os.path.expanduser(base_directory)
    base_directory = os.path.normpath(base_directory)

    if not os.path.exists(base_directory):
        return {
            "status": "error",
            "matches": [],
            "message": f"Base directory does not exist: {base_directory}"
        }

    if not os.path.isdir(base_directory):
        return {
            "status": "error",
            "matches": [],
            "message": f"Base directory is not a directory: {base_directory}"
        }

    pattern = pattern.replace("/", "\\")
    pattern = os.path.expanduser(pattern)
    pattern = os.path.normpath(pattern)

    # If user passes a path, only match on the basename
    file_pattern = os.path.basename(pattern) if (os.path.isabs(pattern) or ("\\" in pattern)) else pattern

    matches = []
    for root, dirs, files in os.walk(base_directory):
        try:
            for name in files:
                if fnmatch.fnmatch(name, file_pattern):
                    matches.append(os.path.abspath(os.path.join(root, name)))
        except PermissionError:
            continue

        if not recursive:
            break

    return {
        "status": "success",
        "matches": matches,
        "message": "" if matches else f"No files matching '{file_pattern}' were found in '{base_directory}'."
    }
