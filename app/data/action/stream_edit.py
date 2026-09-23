from agent_core import action

@action(
    name="stream_edit",
    description="Performs string replacement in a file. You MUST use read_file first to read the file before editing. The old_string must be unique in the file - if it appears multiple times, use replace_all=True or provide more context to make it unique. Supports regex patterns with regex=True and case-insensitive matching with ignore_case=True.",
    mode="CLI",
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "file_path": {
            "type": "string",
            "example": "/path/to/file.py",
            "description": "Absolute path to the file to edit. The file must exist.",
        },
        "old_string": {
            "type": "string",
            "example": "def old_function():",
            "description": "The text or regex pattern to find and replace. Must match exactly including whitespace and indentation (unless regex=True). The edit will FAIL if old_string is not found or appears multiple times (unless replace_all=True).",
        },
        "new_string": {
            "type": "string",
            "example": "def new_function():",
            "description": "The text to replace old_string with. Can be empty string to delete the old_string. When regex=True, can use backreferences like \\1, \\2.",
        },
        "replace_all": {
            "type": "boolean",
            "example": False,
            "description": "If True, replace ALL occurrences of old_string. If False (default), the edit fails if old_string appears more than once.",
            "default": False,
        },
        "regex": {
            "type": "boolean",
            "example": False,
            "description": "If True, treat old_string as a regex pattern. If False (default), treat as literal string.",
            "default": False,
        },
        "ignore_case": {
            "type": "boolean",
            "example": False,
            "description": "If True, perform case-insensitive matching. If False (default), matching is case-sensitive.",
            "default": False,
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "message": {
            "type": "string",
            "example": "Successfully replaced 1 occurrence(s)",
            "description": "Description of what was done or error message if failed.",
        },
        "occurrences_replaced": {
            "type": "integer",
            "example": 1,
            "description": "Number of occurrences that were replaced.",
        },
    },
    test_payload={
        "file_path": "/tmp/test_file.txt",
        "old_string": "old text",
        "new_string": "new text",
        "replace_all": False,
        "regex": False,
        "ignore_case": False,
        "simulated_mode": True,
    },
)
def stream_edit_action(input_data: dict) -> dict:
    import os
    import re

    from app.utils.file_locks import get_file_lock

    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "status": "success",
            "message": "Successfully replaced 1 occurrence(s)",
            "occurrences_replaced": 1,
        }
    
    try:
        file_path = input_data.get("file_path")
        old_string = input_data.get("old_string")
        new_string = input_data.get("new_string", "")
        replace_all = input_data.get("replace_all", False)
        use_regex = input_data.get("regex", False)
        ignore_case = input_data.get("ignore_case", False)

        # Validate inputs
        if not file_path:
            return {
                "status": "error",
                "message": "file_path is required",
                "occurrences_replaced": 0,
            }

        if old_string is None:
            return {
                "status": "error",
                "message": "old_string is required",
                "occurrences_replaced": 0,
            }

        if not os.path.isfile(file_path):
            return {
                "status": "error",
                "message": f"File does not exist: {file_path}",
                "occurrences_replaced": 0,
            }

        if old_string == new_string and not use_regex:
            return {
                "status": "error",
                "message": "old_string and new_string are identical - no change needed",
                "occurrences_replaced": 0,
            }
        lock = get_file_lock(file_path)

        with lock:
            # Read RAW so we can detect the file's line ending and preserve it
            # on write. Text mode would translate CRLF->LF; writing LF back then
            # silently rewrites every line of a CRLF file (a spurious full-file
            # diff, and it fights git's autocrlf on the next checkout).
            with open(file_path, "rb") as f:
                content_raw = f.read().decode("utf-8", errors="replace")
            crlf_count = content_raw.count("\r\n")
            lf_count = content_raw.count("\n") - crlf_count
            uses_crlf = crlf_count > 0 and crlf_count >= lf_count

            # Match in LF space. read_file shows the agent LF-normalized text
            # (universal newlines), so old_string is LF; normalize content and
            # both strings to the same space so a CRLF file never mismatches.
            content = content_raw.replace("\r\n", "\n").replace("\r", "\n")
            old_string = old_string.replace("\r\n", "\n").replace("\r", "\n")
            new_string = new_string.replace("\r\n", "\n").replace("\r", "\n")

            # Count occurrences and perform replacement
            if use_regex:
                # Regex mode
                flags = re.IGNORECASE if ignore_case else 0
                try:
                    pattern = re.compile(old_string, flags)
                except re.error as e:
                    return {
                        "status": "error",
                        "message": f"Invalid regex pattern: {e}",
                        "occurrences_replaced": 0,
                    }

                matches = pattern.findall(content)
                count = len(matches)

                if count == 0:
                    return {
                        "status": "error",
                        "message": "Pattern not found in file.",
                        "occurrences_replaced": 0,
                    }

                if count > 1 and not replace_all:
                    return {
                        "status": "error",
                        "message": f"Pattern matches {count} times in file. Either provide more specific pattern, or set replace_all=True to replace all occurrences.",
                        "occurrences_replaced": 0,
                    }

                if replace_all:
                    new_content = pattern.sub(new_string, content)
                else:
                    new_content = pattern.sub(new_string, content, count=1)
            else:
                # Literal string mode
                if ignore_case:
                    # Case-insensitive literal string matching
                    pattern = re.compile(re.escape(old_string), re.IGNORECASE)
                    matches = pattern.findall(content)
                    count = len(matches)

                    if count == 0:
                        return {
                            "status": "error",
                            "message": "old_string not found in file. Make sure the text matches exactly including whitespace and indentation.",
                            "occurrences_replaced": 0,
                        }

                    if count > 1 and not replace_all:
                        return {
                            "status": "error",
                            "message": f"old_string appears {count} times in file. Either provide more context to make it unique, or set replace_all=True to replace all occurrences.",
                            "occurrences_replaced": 0,
                        }

                    if replace_all:
                        new_content = pattern.sub(new_string, content)
                    else:
                        new_content = pattern.sub(new_string, content, count=1)
                else:
                    # Case-sensitive literal matching, exact first.
                    count = content.count(old_string)
                    ws_pattern = None

                    if count == 0:
                        # read_file strips trailing whitespace per line, so the
                        # agent's old_string routinely lacks trailing spaces/tabs
                        # the file actually has -> exact match misses. Retry
                        # allowing trailing whitespace at each line end. Every
                        # non-whitespace character (including indentation) must
                        # still match, so this can never hit unrelated text.
                        ws_pattern = re.compile(
                            "\n".join(
                                re.escape(ln.rstrip()) + r"[ \t]*"
                                for ln in old_string.split("\n")
                            )
                        )
                        count = len(ws_pattern.findall(content))
                        if count == 0:
                            ws_pattern = None

                    if count == 0:
                        return {
                            "status": "error",
                            "message": (
                                "old_string not found in file. It must match the "
                                "file's exact characters: quotes ('/\"/`), internal "
                                "spacing, and indentation. If the target line is "
                                "long, re-read it with a larger max_line_length in "
                                "case read_file truncated it with '...'."
                            ),
                            "occurrences_replaced": 0,
                        }

                    if count > 1 and not replace_all:
                        return {
                            "status": "error",
                            "message": f"old_string appears {count} times in file. Either provide more context to make it unique, or set replace_all=True to replace all occurrences.",
                            "occurrences_replaced": 0,
                        }

                    if ws_pattern is not None:
                        # Replace via the whitespace-tolerant pattern. A function
                        # replacement keeps backslashes in new_string literal (no
                        # regex backreference interpretation).
                        new_content = ws_pattern.sub(
                            lambda _m: new_string,
                            content,
                            count=0 if replace_all else 1,
                        )
                    elif replace_all:
                        new_content = content.replace(old_string, new_string)
                    else:
                        new_content = content.replace(old_string, new_string, 1)

            # Write with the file's ORIGINAL line ending restored, so an edit
            # to a CRLF file stays CRLF instead of being converted to LF.
            if uses_crlf:
                new_content = new_content.replace("\n", "\r\n")
            with open(file_path, "w", encoding="utf-8", newline="") as f:
                f.write(new_content)

            return {
                "status": "success",
                "message": f"Successfully replaced {count} occurrence(s)",
                "occurrences_replaced": count,
            }

    except Exception as e:
        return {"status": "error", "message": str(e), "occurrences_replaced": 0}
