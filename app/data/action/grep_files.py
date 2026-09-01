from agent_core import action

_INPUT_SCHEMA = {
    "pattern": {
        "type": "string",
        "example": "def \\w+\\(",
        "description": "Regex pattern to search for. Supports full regex syntax (e.g., 'def \\w+\\(' to find function definitions, 'TODO:.*' to find TODOs). For literal text search, just use the plain text (special regex chars will need escaping).",
    },
    "path": {
        "type": "string",
        "example": "/workspace/project",
        "description": "File or directory path to search in. If a directory, searches all files recursively. If a file, searches only that file. Defaults to current working directory if not provided.",
    },
    "glob": {
        "type": "string",
        "example": "*.py",
        "description": "Glob filter (e.g. '*.py', '*.{js,ts}', 'test_*.py', 'src/**/*.ts'). Brace alternatives are expanded. A pattern with no '/' matches the FILENAME anywhere in the tree; one with a '/' matches the path and is also tried unanchored, so 'src/**/*.ts' finds 'frontend/src/app/x.ts'. Only applies when path is a directory.",
    },
    "file_type": {
        "type": "string",
        "example": "py",
        "description": "Filter by file extension. Accepts one ('py') or a comma-separated list ('ts,tsx'). NOTE: a single extension is exact — 'ts' does NOT include .tsx, so use 'ts,tsx' for a React codebase. Shorthand for glob; if both are given, glob wins.",
    },
    "output_mode": {
        "type": "string",
        "example": "content",
        "description": "Controls what is returned. 'files_with_matches' (default): returns only file paths that contain matches. 'content': returns matching lines with line numbers and optional context. 'count': returns the number of matches per file.",
    },
    "case_insensitive": {
        "type": "boolean",
        "example": True,
        "description": "If true, search is case-insensitive. Default is false (case-sensitive).",
    },
    "before_context": {
        "type": "integer",
        "example": 2,
        "description": "Number of lines to show BEFORE each match. Only applies when output_mode is 'content'. Default is 0.",
    },
    "after_context": {
        "type": "integer",
        "example": 2,
        "description": "Number of lines to show AFTER each match. Only applies when output_mode is 'content'. Default is 0.",
    },
    "context": {
        "type": "integer",
        "example": 3,
        "description": "Number of context lines to show both before AND after each match (shorthand for setting before_context and after_context to the same value). Only applies when output_mode is 'content'. Overridden by explicit before_context/after_context if provided.",
    },
    "multiline": {
        "type": "boolean",
        "example": False,
        "description": "If true, enables multiline mode where '.' matches newlines and patterns can span across lines. Default is false.",
    },
    "head_limit": {
        "type": "integer",
        "example": 50,
        "description": "Maximum number of results to return. For 'files_with_matches': max file paths. For 'content': max output lines. For 'count': max file entries. Default is 250. Pass 0 for unlimited results (no truncation). If results are truncated, the applied_limit field in the response tells you it happened — use offset to paginate through the rest. Note: 'content' output is ALSO byte-capped independently of this (each line trimmed to 500 chars, whole payload to 40000 chars) so a file with very long lines cannot flood the context; the message field says so when it happens.",
    },
    "offset": {
        "type": "integer",
        "example": 0,
        "description": "Number of results to skip before returning. Use with head_limit for pagination. Default is 0.",
    },
}

_OUTPUT_SCHEMA = {
    "status": {
        "type": "string",
        "example": "success",
        "description": "'success' or 'error'.",
    },
    "message": {
        "type": "string",
        "example": "Found matches in 5 files",
        "description": "Summary message or error description.",
    },
    "mode": {
        "type": "string",
        "example": "content",
        "description": "The output mode that was used.",
    },
    "num_files": {
        "type": "integer",
        "example": 5,
        "description": "Number of files that contained matches.",
    },
    "filenames": {
        "type": "array",
        "example": ["/workspace/project/main.py", "/workspace/project/utils.py"],
        "description": "List of file paths that contained matches.",
    },
    "content": {
        "type": "string",
        "example": "File: /workspace/main.py\n10:def hello():\n11-    pass\n--\n25:def world():\n26-    return 1\n",
        "description": "Matching lines with line numbers. Match lines use ':' after the line number (e.g., '10:matched line'), context lines use '-' (e.g., '11-context line'). Non-contiguous groups are separated by '--'. For single-file searches, the filepath is shown once at the top to save tokens. For multi-file searches, each file section is prefixed with 'File: path'. Only populated when output_mode is 'content'.",
    },
    "num_lines": {
        "type": "integer",
        "example": 15,
        "description": "Number of content lines returned. Only populated when output_mode is 'content'.",
    },
    "num_matches": {
        "type": "integer",
        "example": 42,
        "description": "Total number of matches across all files. Only populated when output_mode is 'count'.",
    },
    "applied_limit": {
        "type": "integer",
        "example": 250,
        "description": "The head_limit that was applied, or null if unlimited (head_limit=0). If your results were truncated to this limit, use offset to paginate through the rest.",
    },
    "applied_offset": {
        "type": "integer",
        "example": 0,
        "description": "The offset that was applied.",
    },
}


@action(
    name="grep_files",
    description=(
        "Searches files for a regex pattern and returns results. "
        "Supports searching a single file or an entire directory recursively. "
        "Three output modes: "
        "'files_with_matches' (default) returns file paths containing matches — use for discovery. "
        "'content' returns matching lines with line numbers and optional before/after context — use to read matched code. "
        "In content mode, match lines use ':' after line number (e.g., '10:matched line'), "
        "context lines use '-' (e.g., '11-context line'), and non-contiguous groups are separated by '--'. "
        "'count' returns match counts per file — use for quick frequency checks. "
        "Supports glob and file_type filtering, case-insensitive search, and multiline patterns. "
        "Use with read_file: first grep_files to find relevant line numbers, then read_file with offset to read that section."
    ),
    mode="CLI",
    platforms=["linux", "windows", "darwin"],
    action_sets=["core"],
    input_schema=_INPUT_SCHEMA,
    output_schema=_OUTPUT_SCHEMA,
    test_payload={
        "pattern": "Mt\\. Fuji|visibility",
        "path": "/path/to/input.txt",
        "output_mode": "content",
        "case_insensitive": True,
        "head_limit": 50,
        "simulated_mode": True,
    },
)
def grep_files(input_data: dict) -> dict:
    """Searches files for a regex pattern and returns results."""
    import os
    import re
    import fnmatch

    # Byte caps on the returned payload. head_limit bounds the number of LINES,
    # which is no bound at all when a "line" is a 160KB MIME header blob (raw
    # Received/DKIM/ARC headers in an externalized get_gmail dump). Without these
    # a single grep can land a ~77k-token event in the event stream, which blows
    # the summarization threshold in one shot. Both are applied AFTER pagination
    # so head_limit/offset still mean what they say.
    MAX_LINE_CHARS = 500
    MAX_CONTENT_CHARS = 40000

    # --- Helper functions (must be inside for sandboxed execution) ---

    def make_error(message):
        return {
            "status": "error",
            "message": message,
            "mode": None,
            "num_files": 0,
            "filenames": [],
            "content": None,
            "num_lines": None,
            "num_matches": None,
            "applied_limit": None,
            "applied_offset": None,
        }

    def expand_braces(pat):
        """Expand {a,b} alternatives into separate patterns.

        fnmatch has no brace support, but THIS TOOL'S OWN SCHEMA advertises
        "*.{js,ts}" as a valid glob. Every agent that followed the docs got a
        silent 0 results — indistinguishable from "the string is not there".
        """
        out = [pat]
        while True:
            grown = []
            changed = False
            for item in out:
                i = item.find("{")
                j = item.find("}", i + 1) if i >= 0 else -1
                if i >= 0 and j > i:
                    head, body, tail = item[:i], item[i + 1 : j], item[j + 1 :]
                    for alt in body.split(","):
                        grown.append(head + alt.strip() + tail)
                    changed = True
                else:
                    grown.append(item)
            out = grown
            if not changed:
                return out

    def glob_hit(rel_path, fname, patterns):
        """Match a file against expanded patterns.

        A pattern with no separator is a NAME pattern ("*.py" anywhere in the
        tree); one with a separator is a PATH pattern ("src/**/*.ts"). The
        old code compared every pattern against the BASENAME only, so any
        path-shaped glob matched nothing, silently.
        """
        for pat in patterns:
            if "/" not in pat and os.sep not in pat:
                if fnmatch.fnmatch(fname, pat):
                    return True
                continue
            norm = rel_path.replace(os.sep, "/")
            if fnmatch.fnmatch(norm, pat):
                return True
            # "**/" must also match ZERO directories: "src/**/*.ts" has to
            # find "src/x.ts", not only "src/a/x.ts".
            flat = pat.replace("**/", "")
            if "**/" in pat and fnmatch.fnmatch(norm, flat):
                return True
            # Unanchored fallback: "src/**/*.ts" should also find
            # "frontend/src/app/x.ts". Strict root-anchoring is defensible,
            # but a false negative here costs far more than a false positive
            # — the caller reads it as "this code does not exist".
            if fnmatch.fnmatch(norm, "*/" + pat) or fnmatch.fnmatch(
                norm, "*/" + flat
            ):
                return True
        return False
    def collect_files(directory, glob_pat=None, max_files=10000):
        SKIP_DIRS = {
            ".git",
            ".svn",
            ".hg",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            ".env",
            ".tox",
            ".mypy_cache",
            ".pytest_cache",
            "dist",
            "build",
            ".idea",
            ".vscode",
        }
        patterns = expand_braces(glob_pat) if glob_pat else None
        collected = []
        stats = {"seen": 0, "skipped_by_glob": 0, "hidden": 0}
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for fname in files:
                if fname.startswith("."):
                    stats["hidden"] += 1
                    continue
                stats["seen"] += 1
                if patterns:
                    rel = os.path.relpath(os.path.join(root, fname), directory)
                    if not glob_hit(rel, fname, patterns):
                        stats["skipped_by_glob"] += 1
                        continue
                collected.append(os.path.join(root, fname))
                if len(collected) >= max_files:
                    return collected, stats
        return collected, stats

    def format_content_lines(
        fpath, lines, sorted_indices, display_map, single_file, first_file
    ):
        result = []
        if single_file:
            if first_file:
                result.append(f"File: {fpath}")
        else:
            if not first_file:
                result.append("--")
            result.append(f"File: {fpath}")

        prev_ln = None
        for ln in sorted_indices:
            if ln >= len(lines):
                continue
            if prev_ln is not None and ln > prev_ln + 1:
                result.append("--")
            separator = ":" if display_map[ln] else "-"
            result.append(f"{ln + 1}{separator}{lines[ln]}")
            prev_ln = ln
        return result

    # --- Main logic ---

    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "status": "success",
            "message": "Found matches in 2 files",
            "mode": "content",
            "num_files": 2,
            "filenames": ["/path/to/input.txt", "/path/to/other.txt"],
            "content": "File: /path/to/input.txt\n10:Mt. Fuji is visible today\n11-The mountain was clear\n--\nFile: /path/to/other.txt\n5:visibility is low\n",
            "num_lines": 5,
            "num_matches": None,
            "applied_limit": 50,
            "applied_offset": 0,
        }

    # --- Parse and validate inputs ---
    pattern_str = input_data.get("pattern")
    if not pattern_str:
        return make_error("pattern is required.")

    search_path = input_data.get("path") or os.getcwd()
    output_mode = input_data.get("output_mode", "files_with_matches")
    if output_mode not in ("files_with_matches", "content", "count"):
        output_mode = "files_with_matches"

    case_insensitive = bool(input_data.get("case_insensitive", False))
    multiline_mode = bool(input_data.get("multiline", False))
    glob_pattern = input_data.get("glob")
    file_type = input_data.get("file_type")

    # Context lines (only for content mode)
    try:
        ctx = int(input_data.get("context", 0))
    except (TypeError, ValueError):
        ctx = 0
    try:
        before_ctx = int(input_data.get("before_context", ctx))
    except (TypeError, ValueError):
        before_ctx = ctx
    try:
        after_ctx = int(input_data.get("after_context", ctx))
    except (TypeError, ValueError):
        after_ctx = ctx
    before_ctx = max(0, before_ctx)
    after_ctx = max(0, after_ctx)

    # Pagination
    raw_limit = input_data.get("head_limit")
    try:
        head_limit = int(raw_limit) if raw_limit is not None else 250
    except (TypeError, ValueError):
        head_limit = 250
    try:
        offset = int(input_data.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if head_limit < 0:
        head_limit = 250
    unlimited = head_limit == 0
    if offset < 0:
        offset = 0

    # --- Compile regex ---
    flags = 0
    if case_insensitive:
        flags |= re.IGNORECASE
    if multiline_mode:
        flags |= re.DOTALL | re.MULTILINE

    try:
        regex = re.compile(pattern_str, flags)
    except re.error as e:
        return make_error(f"Invalid regex pattern: {e}")

    # --- Collect files to search ---
    if not os.path.exists(search_path):
        return make_error(f"Path does not exist: {search_path}")

    active_glob = None
    collect_stats = None
    if os.path.isfile(search_path):
        files_to_search = [search_path]
    else:
        if glob_pattern:
            active_glob = glob_pattern
        elif file_type:
            # file_type now accepts a list ("ts,tsx"). A bare "ts" silently
            # excludes every .tsx file — i.e. most of a React codebase — and
            # the caller only ever saw "0 matches" for it.
            exts = [
                t.strip().lstrip(".")
                for t in str(file_type).split(",")
                if t.strip()
            ]
            if len(exts) > 1:
                active_glob = "*.{" + ",".join(exts) + "}"
            elif exts:
                active_glob = f"*.{exts[0]}"
        files_to_search, collect_stats = collect_files(search_path, active_glob)

    # --- Search each file ---
    matched_filenames = []
    content_lines = []
    total_match_count = 0
    count_entries = []
    is_single_file = len(files_to_search) == 1

    for fpath in files_to_search:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                file_content = f.read()
        except (OSError, IOError):
            continue

        if not file_content:
            continue

        lines = file_content.split("\n")

        if multiline_mode:
            matches = list(regex.finditer(file_content))
            if not matches:
                continue
            matched_line_nums = set()
            for m in matches:
                start_line = file_content[: m.start()].count("\n")
                end_line = file_content[: m.end()].count("\n")
                for ln in range(start_line, end_line + 1):
                    matched_line_nums.add(ln)
        else:
            matched_line_nums = set()
            for i, line in enumerate(lines):
                if regex.search(line):
                    matched_line_nums.add(i)

        if not matched_line_nums:
            continue

        matched_filenames.append(fpath)
        match_count = len(matched_line_nums)
        total_match_count += match_count

        if output_mode == "count":
            count_entries.append(f"{fpath}: {match_count}")
        elif output_mode == "content":
            display_map = {}
            for ln in matched_line_nums:
                display_map[ln] = True
                for ctx_ln in range(
                    max(0, ln - before_ctx), min(len(lines), ln + after_ctx + 1)
                ):
                    if ctx_ln not in display_map:
                        display_map[ctx_ln] = False

            sorted_indices = sorted(display_map.keys())
            file_lines = format_content_lines(
                fpath,
                lines,
                sorted_indices,
                display_map,
                is_single_file,
                first_file=(len(content_lines) == 0),
            )
            content_lines.extend(file_lines)

    # --- Apply pagination and build output ---
    def paginate(items):
        after_offset = items[offset:]
        if unlimited:
            return after_offset
        return after_offset[:head_limit]

    def clamp_line(line):
        """Trim one output line to MAX_LINE_CHARS, keeping the 'NN:' prefix."""
        if len(line) <= MAX_LINE_CHARS:
            return line, 0
        dropped = len(line) - MAX_LINE_CHARS
        return (
            f"{line[:MAX_LINE_CHARS]}… [line truncated, {dropped} chars dropped]",
            dropped,
        )

    def clamp_content(lines):
        """Apply the per-line and total byte caps. Returns (lines, note)."""
        clamped = []
        truncated_lines = 0
        used = 0
        stopped_at = None
        for i, line in enumerate(lines):
            text, dropped = clamp_line(line)
            if dropped:
                truncated_lines += 1
            if used + len(text) + 1 > MAX_CONTENT_CHARS:
                stopped_at = i
                break
            clamped.append(text)
            used += len(text) + 1

        notes = []
        if truncated_lines:
            notes.append(
                f"{truncated_lines} line(s) were trimmed to {MAX_LINE_CHARS} chars"
            )
        if stopped_at is not None:
            notes.append(
                f"output capped at {MAX_CONTENT_CHARS} chars after {stopped_at} of "
                f"{len(lines)} line(s) — narrow the pattern or use offset={offset + stopped_at} "
                "to continue"
            )
        return clamped, "; ".join(notes)

    def _with_note(msg):
        note = search_note()
        return f"{msg} — {note}" if note else msg

    def search_note():
        """Explain an empty result instead of just reporting one.

        A 0 from a filter that ate every candidate used to read exactly like
        a 0 from a genuine absence. Observed twice in production: an agent
        turned "0 matches" into a confident structural claim ("the handler
        must live in the frontend", "the code must be bundled elsewhere") and
        acted on it for half an hour. The file it wanted was four lines long
        and sat in the directory it had just searched.
        """
        if matched_filenames or collect_stats is None:
            return ""
        skipped = collect_stats.get("skipped_by_glob", 0)
        seen = collect_stats.get("seen", 0)
        hidden = collect_stats.get("hidden", 0)
        if not files_to_search:
            which = "glob" if glob_pattern else "file_type"
            return (
                f"NOTHING WAS SEARCHED: the {which} filter {active_glob!r} "
                f"excluded all {seen} file(s) under {search_path}. This is "
                "NOT evidence the pattern is absent — widen or drop the "
                "filter and search again."
            )
        parts = [f"searched {len(files_to_search)} file(s)"]
        if skipped:
            parts.append(
                f"{skipped} more were excluded by {active_glob!r} and never "
                "looked at"
            )
        if hidden:
            parts.append(f"{hidden} dot-file(s) are always skipped")
        return "no match after " + "; ".join(parts) + "."

    effective_limit = None if unlimited else head_limit

    if output_mode == "files_with_matches":
        total = len(matched_filenames)
        paginated = paginate(matched_filenames)
        return {
            "status": "success",
            "message": _with_note(f"Found matches in {total} file(s)"),
            "mode": "files_with_matches",
            "num_files": total,
            "filenames": paginated,
            "content": None,
            "num_lines": None,
            "num_matches": None,
            "applied_limit": effective_limit,
            "applied_offset": offset,
        }

    elif output_mode == "content":
        paginated, cap_note = clamp_content(paginate(content_lines))
        content_str = "\n".join(paginated)
        if paginated:
            content_str += "\n"
        message = (
            f"Found {total_match_count} match(es) in {len(matched_filenames)} file(s)"
        )
        if cap_note:
            message += f" ({cap_note})"
        message = _with_note(message)
        return {
            "status": "success",
            "message": message,
            "mode": "content",
            "num_files": len(matched_filenames),
            # Content mode already carries each path inline in `content`; echoing an
            # unbounded filename list on top of it is pure token cost on a wide search.
            "filenames": matched_filenames[:100],
            "content": content_str,
            "num_lines": len(paginated),
            "num_matches": None,
            "applied_limit": effective_limit,
            "applied_offset": offset,
        }

    else:  # count
        paginated = paginate(count_entries)
        return {
            "status": "success",
            "message": _with_note(
                f"Total: {total_match_count} match(es) in "
                f"{len(matched_filenames)} file(s)"
            ),
            "mode": "count",
            "num_files": len(matched_filenames),
            "filenames": matched_filenames,
            "content": "\n".join(paginated) + "\n" if paginated else "",
            "num_lines": None,
            "num_matches": total_match_count,
            "applied_limit": effective_limit,
            "applied_offset": offset,
        }
