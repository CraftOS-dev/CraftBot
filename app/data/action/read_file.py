from agent_core import action


@action(
    name="read_file",
    description="Reads a file and returns its contents with line numbers. PDF files are returned as their extracted text (text layer only, one '## Page N' heading per page). By default reads up to 2000 lines from the beginning. Use offset and limit parameters to read specific sections of large files. For searching within files, use grep_files instead.",
    mode="CLI",
    action_sets=["core"],
    input_schema={
        "file_path": {
            "type": "string",
            "example": "/workspace/document.txt",
            "description": "Absolute path to the text file to read.",
        },
        "encoding": {
            "type": "string",
            "example": "utf-8",
            "description": "File encoding. Defaults to 'utf-8'.",
        },
        "offset": {
            "type": "integer",
            "example": 0,
            "description": "Line number to start reading from (0-based). Default is 0 (start from beginning).",
        },
        "limit": {
            "type": "integer",
            "example": 500,
            "description": "Maximum number of lines to read. Default is 500. Use smaller values for focused reading of large files.",
        },
        "max_line_length": {
            "type": "integer",
            "example": 500,
            "description": "Maximum characters per line before truncation. Default is 500. Lines exceeding this will be truncated with '...'.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "content": {
            "type": "string",
            "example": "     1\tFirst line\n     2\tSecond line\n",
            "description": "File content with line numbers in 'cat -n' format. Each line is prefixed with its 1-based line number and a tab.",
        },
        "total_lines": {
            "type": "integer",
            "example": 150,
            "description": "Total number of lines in the file.",
        },
        "lines_returned": {
            "type": "integer",
            "example": 150,
            "description": "Number of lines actually returned in this response.",
        },
        "offset": {
            "type": "integer",
            "example": 0,
            "description": "The offset that was used for this read.",
        },
        "has_more": {
            "type": "boolean",
            "example": False,
            "description": "True if there are more lines beyond what was returned. Use offset + lines_returned for the next read.",
        },
        "message": {
            "type": "string",
            "description": "Error message if status is 'error'.",
        },
    },
    test_payload={
        "file_path": "/workspace/test.txt",
        "offset": 0,
        "limit": 2000,
        "simulated_mode": True,
    },
)
def read_file(input_data: dict) -> dict:
    import os

    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "status": "success",
            "content": "     1\tTest file content\n     2\tSecond line\n",
            "total_lines": 2,
            "lines_returned": 2,
            "offset": 0,
            "has_more": False,
        }

    file_path = input_data.get("file_path", "")
    encoding = input_data.get("encoding", "utf-8")

    # Parse offset with default
    try:
        offset = int(input_data.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0

    # Parse limit with default
    try:
        limit = int(input_data.get("limit", 2000))
    except (TypeError, ValueError):
        limit = 2000

    # Parse max_line_length with default
    try:
        max_line_length = int(input_data.get("max_line_length", 2000))
    except (TypeError, ValueError):
        max_line_length = 2000

    # Normalize values
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 2000
    if max_line_length <= 0:
        max_line_length = 2000

    if not file_path:
        return {
            "status": "error",
            "content": "",
            "total_lines": 0,
            "lines_returned": 0,
            "offset": 0,
            "has_more": False,
            "message": "file_path is required.",
        }

    if not os.path.isfile(file_path):
        return {
            "status": "error",
            "content": "",
            "total_lines": 0,
            "lines_returned": 0,
            "offset": 0,
            "has_more": False,
            "message": f"File not found: {file_path}",
        }

    try:
        if file_path.lower().endswith(".pdf"):
            # PDFs: extracted text layer only (images ignored) — the same
            # preprocessing the memory indexer uses, so what this action
            # returns matches what got indexed.
            from pathlib import Path

            from agent_core.core.impl.memory.text_extract import extract_text

            all_lines = [
                line + "\n" for line in extract_text(Path(file_path)).splitlines()
            ]
        else:
            with open(file_path, "r", encoding=encoding, errors="replace") as f:
                all_lines = f.readlines()

        total_lines = len(all_lines)

        # Apply offset and limit
        end_idx = min(offset + limit, total_lines)
        selected_lines = all_lines[offset:end_idx]

        # Total byte cap on the payload. `limit` bounds LINES and
        # `max_line_length` bounds each line, but limit*max_line_length is
        # multi-megabyte in the worst case. read_file is exempt from event-stream
        # externalization (it IS the retrieval path for externalized content), so
        # an uncapped read lands verbatim in the prompt and can blow the
        # summarization threshold on its own. 80000 chars ~= 20k tokens, safely
        # under the 30k threshold; the agent pages with offset for the rest.
        MAX_CONTENT_CHARS = 80000

        # Format with line numbers (1-based, matching cat -n format)
        formatted_lines = []
        used = 0
        capped_at = None
        for i, line in enumerate(selected_lines, start=offset + 1):
            line_content = line.rstrip("\n\r")
            # Truncate long lines
            if len(line_content) > max_line_length:
                line_content = line_content[:max_line_length] + "..."
            # Format line number with right-alignment (6 chars) + tab + content
            formatted = f"{i:>6}\t{line_content}"
            if used + len(formatted) + 1 > MAX_CONTENT_CHARS:
                capped_at = i
                break
            formatted_lines.append(formatted)
            used += len(formatted) + 1

        content = "\n".join(formatted_lines)
        if formatted_lines:
            content += "\n"

        lines_returned = len(formatted_lines)
        has_more = (offset + lines_returned) < total_lines

        result = {
            "status": "success",
            "content": content,
            "total_lines": total_lines,
            "lines_returned": lines_returned,
            "offset": offset,
            "has_more": has_more,
        }
        if capped_at is not None:
            result["message"] = (
                f"Output capped at {MAX_CONTENT_CHARS} chars; stopped at line "
                f"{capped_at}. Call again with offset={offset + lines_returned} to continue."
            )
        return result
    except Exception as e:
        return {
            "status": "error",
            "content": "",
            "total_lines": 0,
            "lines_returned": 0,
            "offset": 0,
            "has_more": False,
            "message": str(e),
        }
