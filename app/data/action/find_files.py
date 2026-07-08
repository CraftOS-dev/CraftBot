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
            "description": "The file name or glob pattern to match. Supports wildcards like * and ?. To match any of several patterns in a single call, join them with '|' or ' OR ' instead of calling find_files multiple times, e.g. '*craftbot*|*craftos*' or '*.jpg OR *.png'.",
        },
        "recursive": {
            "type": "boolean",
            "example": True,
            "description": "Whether to search directories recursively. Default is true.",
        },
        "base_directory": {
            "type": "string",
            "example": "/home/user/Documents",
            "description": "Absolute path to the base directory to start searching from. Use full absolute paths (e.g., /home/user/Documents or /Users/name/Desktop). To search multiple roots in one call, join them with '|' (e.g. '/home/user|/mnt/data'). Ignored if all_drives is true.",
        },
        "all_drives": {
            "type": "boolean",
            "example": False,
            "description": "If true, search every local fixed drive/mount in one call instead of just base_directory (which is then ignored). Use this instead of calling find_files once per drive.",
        },
        "limit": {
            "type": "integer",
            "example": 500,
            "description": "Optional cap on the total number of matches returned across all searched roots. Useful with all_drives or broad patterns to avoid extremely large result sets. Default: unbounded.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "matches": {
            "type": "array",
            "items": {"type": "string"},
            "example": [
                "/home/user/Documents/file1.pdf",
                "/home/user/Documents/reports/file2.pdf",
            ],
        },
        "message": {"type": "string", "example": "No files matched."},
    },
    test_payload={
        "pattern": "*.pdf",
        "recursive": True,
        "base_directory": "/home/user/Documents",
        "simulated_mode": True,
    },
)
def find_file_by_name(input_data: dict) -> dict:
    import os

    from app.utils import file_index

    pattern = (input_data.get("pattern") or "").strip()
    recursive = bool(input_data.get("recursive", True))
    all_drives = bool(input_data.get("all_drives", False))
    base_directory = (input_data.get("base_directory") or "").strip()
    limit = input_data.get("limit")

    if not pattern:
        return {"status": "error", "matches": [], "message": "Pattern is required."}

    if all_drives:
        base_directory = ""
    else:
        roots, error = file_index.resolve_roots(base_directory, windows=False)
        if error:
            return error
        base_directory = "|".join(roots)

    # Normalize the pattern (if user passes a path, only use its basename as the match pattern)
    pattern = os.path.expanduser(pattern)
    pattern = os.path.normpath(pattern)
    file_pattern = (
        os.path.basename(pattern)
        if (os.path.isabs(pattern) or os.sep in pattern)
        else pattern
    )

    return file_index.find_files(
        base_directory, file_pattern, recursive, all_drives, limit
    )


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
            "description": "The file name or glob pattern to match. Supports wildcards like * and ?. To match any of several patterns in a single call, join them with '|' or ' OR ' instead of calling find_files multiple times, e.g. '*craftbot*|*craftos*' or '*.jpg OR *.png'.",
        },
        "recursive": {
            "type": "boolean",
            "example": True,
            "description": "Whether to search directories recursively. Default is true.",
        },
        "base_directory": {
            "type": "string",
            "example": "C:/Users/user/Documents",
            "description": "Absolute path to the base directory to start searching from. Use full absolute paths (e.g., C:/Users/user/Documents or D:/Projects). To search multiple drives/roots in one call, join them with '|' (e.g. 'C:/|D:/'). Ignored if all_drives is true.",
        },
        "all_drives": {
            "type": "boolean",
            "example": False,
            "description": "If true, search every local fixed drive in one call instead of just base_directory (which is then ignored). Use this instead of calling find_files once per drive.",
        },
        "limit": {
            "type": "integer",
            "example": 500,
            "description": "Optional cap on the total number of matches returned across all searched roots. Useful with all_drives or broad patterns to avoid extremely large result sets. Default: unbounded.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "matches": {
            "type": "array",
            "items": {"type": "string"},
            "example": [
                "C:/Users/user/Documents/file1.pdf",
                "C:/Users/user/Documents/reports/file2.pdf",
            ],
        },
        "message": {"type": "string", "example": "No files matched."},
    },
    test_payload={
        "pattern": "*.pdf",
        "recursive": True,
        "base_directory": "C:/Users/user/Documents",
        "simulated_mode": True,
    },
)
def find_file_by_name_windows(input_data: dict) -> dict:
    import os

    from app.utils import file_index

    pattern = (input_data.get("pattern") or "").strip()
    recursive = bool(input_data.get("recursive", True))
    all_drives = bool(input_data.get("all_drives", False))
    base_directory = (input_data.get("base_directory") or "").strip()
    limit = input_data.get("limit")

    if not pattern:
        return {"status": "error", "matches": [], "message": "Pattern is required."}

    if all_drives:
        base_directory = ""
    else:
        roots, error = file_index.resolve_roots(base_directory, windows=True)
        if error:
            return error
        base_directory = "|".join(roots)

    pattern = pattern.replace("/", "\\")
    pattern = os.path.expanduser(pattern)
    pattern = os.path.normpath(pattern)

    # If user passes a path, only match on the basename
    file_pattern = (
        os.path.basename(pattern)
        if (os.path.isabs(pattern) or ("\\" in pattern))
        else pattern
    )

    return file_index.find_files(
        base_directory, file_pattern, recursive, all_drives, limit
    )
