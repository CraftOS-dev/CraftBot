from agent_core import action


@action(
    name="web_fetch",
    description=(
        "Fetches a URL and returns cleaned text/markdown content. "
        "Use web_search first to find URLs, then web_fetch to read them. "
        "Two modes: 'full' (default) returns extracted page content up to max_content_length chars. "
        "'title' returns only the page title (cheap, no content extraction). "
        "When content exceeds max_content_length, the full content is saved to a temp file "
        "and content_file path is returned — use grep_files to search it or read_file with offset/limit to paginate. "
        "HTTP is auto-upgraded to HTTPS (except localhost). Follows up to 10 redirects automatically."
    ),
    mode="CLI",
    action_sets=["core"],
    input_schema={
        "url": {
            "type": "string",
            "example": "https://example.com/article",
            "description": "The URL to fetch content from. Must be a valid http(s) URL.",
            "required": True,
        },
        "mode": {
            "type": "string",
            "example": "full",
            "description": "What to return. 'full' (default): extracted page content up to max_content_length, overflow saved to content_file. 'title': only the page title, no content extraction.",
        },
        "timeout": {
            "type": "number",
            "example": 20,
            "description": "Request timeout in seconds. Defaults to 20.",
        },
        "max_content_length": {
            "type": "integer",
            "example": 5000,
            "description": "Maximum content length in characters returned inline. Content beyond this is saved to content_file — use grep_files to search it or read_file with offset/limit to paginate through it. Defaults to 5000. Pass 0 to return all content inline (use sparingly — large pages waste tokens).",
        },
        "use_jina_fallback": {
            "type": "boolean",
            "example": True,
            "description": "Use Jina Reader API as fallback for JS-rendered sites when static extraction yields too little content. Defaults to True.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "status_code": {
            "type": "integer",
            "example": 200,
            "description": "HTTP status code (e.g., 200, 404, 500).",
        },
        "status_text": {
            "type": "string",
            "example": "OK",
            "description": "HTTP status reason (e.g., 'OK', 'Not Found').",
        },
        "url": {
            "type": "string",
            "description": "The final URL after following redirects.",
        },
        "title": {"type": "string", "description": "The page title, if extracted."},
        "content": {
            "type": "string",
            "description": "The extracted page content in markdown/text format, up to max_content_length chars. Empty when mode is 'title'.",
        },
        "content_length": {
            "type": "integer",
            "description": "Length of the inline content in characters.",
        },
        "total_content_length": {
            "type": "integer",
            "description": "Total length of the full extracted content before truncation. Compare with content_length to know how much was cut.",
        },
        "was_truncated": {
            "type": "boolean",
            "description": "True if content was truncated to max_content_length. When true, content_file contains the full content — use grep_files to search it or read_file with offset/limit to paginate.",
        },
        "content_file": {
            "type": "string",
            "description": "Absolute path to the full content file when was_truncated is true. Use grep_files(pattern, path=content_file) to search for specific information, or read_file(file_path=content_file, offset=N, limit=M) to paginate. Null if content was not truncated.",
        },
        "message": {"type": "string", "description": "Error or informational message."},
    },
    requirement=["requests", "beautifulsoup4", "trafilatura", "lxml"],
    test_payload={
        "url": "https://example.com/article",
        "timeout": 20,
        "simulated_mode": True,
    },
)
def web_fetch(input_data: dict) -> dict:
    """Fetches a URL and returns cleaned text/markdown content."""
    import re
    import os
    import tempfile
    from urllib.parse import urlparse
    from datetime import datetime, timezone
    from app.errors import make_error as catalog_make_error

    # --- Helper functions (must be inside for sandboxed execution) ---

    def make_error(message, err_url="", status_code=0, status_text=""):
        return {
            "status": "error",
            "status_code": status_code,
            "status_text": status_text,
            "url": err_url,
            "title": "",
            "content": "",
            "content_length": 0,
            "total_content_length": 0,
            "was_truncated": False,
            "content_file": None,
            "message": message,
        }

    def make_result(
        res_url,
        title,
        content,
        total_content_length,
        status_code,
        status_text,
        was_truncated=False,
        content_file=None,
        message="",
    ):
        return {
            "status": "success",
            "status_code": status_code,
            "status_text": status_text,
            "url": res_url,
            "title": title or "",
            "content": content,
            "content_length": len(content),
            "total_content_length": total_content_length,
            "was_truncated": was_truncated,
            "content_file": content_file,
            "message": message,
        }

    def save_content_file(content, file_url, sess_id):
        save_dir = None
        if sess_id:
            try:
                current = os.path.abspath(__file__)
                for _ in range(10):
                    current = os.path.dirname(current)
                    if os.path.isdir(os.path.join(current, "agent_file_system")):
                        save_dir = os.path.join(
                            current, "agent_file_system", "workspace", "tmp", sess_id
                        )
                        break
            except Exception:
                pass

        if not save_dir:
            save_dir = tempfile.gettempdir()

        os.makedirs(save_dir, exist_ok=True)

        try:
            domain = urlparse(file_url).hostname or "unknown"
            domain = domain.replace(".", "_")
        except Exception:
            domain = "unknown"

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S%f")
        filename = f"web_fetch_{domain}_{ts}.md"
        file_path = os.path.join(save_dir, filename)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"<!-- Source: {file_url} -->\n\n")
            f.write(content)

        return file_path

    # --- Main logic ---

    simulated_mode = input_data.get("simulated_mode", False)
    url = str(input_data.get("url", "")).strip()
    fetch_mode = str(input_data.get("mode", "full")).strip().lower()
    if fetch_mode not in ("full", "title"):
        fetch_mode = "full"
    timeout = float(input_data.get("timeout", 20))
    raw_max = input_data.get("max_content_length")
    try:
        max_content_length = int(raw_max) if raw_max is not None else 5000
    except (TypeError, ValueError):
        max_content_length = 5000
    if max_content_length < 0:
        max_content_length = 5000
    unlimited = max_content_length == 0
    use_jina_fallback = input_data.get("use_jina_fallback", True)
    session_id = input_data.get("_session_id", "")

    # --- Validate URL ---
    if not url:
        return make_error("URL is required.")

    # Auto-upgrade HTTP to HTTPS (except localhost)
    if url.startswith("http://"):
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if host not in ("localhost", "127.0.0.1", "::1"):
                url = "https://" + url[7:]
        except Exception:
            url = "https://" + url[7:]

    if not re.match(r"^https?://", url, re.I):
        return make_error("A valid http(s) URL is required.", url)

    # --- Simulated mode ---
    if simulated_mode:
        mock_content = (
            "# Test Page Title\n\n"
            "This is simulated content fetched from the URL.\n\n"
            "## Main Content\n\n"
            "- Point 1: Important information\n"
            "- Point 2: More details\n"
            "- Point 3: Additional context\n\n"
            "## Summary\n\n"
            "This is a test page demonstrating the web_fetch action."
        )
        if fetch_mode == "title":
            return make_result(url, "Test Page Title", "", 0, 200, "OK")
        return make_result(
            url, "Test Page Title", mock_content, len(mock_content), 200, "OK"
        )

    # --- Fetch the URL ---
    try:
        import requests
        from bs4 import BeautifulSoup
        import trafilatura

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # Fetch content — follow up to 10 redirects automatically
        response = requests.get(
            url, headers=headers, timeout=timeout, allow_redirects=True, stream=True
        )
        response.raise_for_status()

        status_code = response.status_code
        status_text = response.reason or ""
        final_url = str(response.url)

        # Check content type
        content_type = response.headers.get("Content-Type", "")
        if not any(
            t in content_type
            for t in ("text/html", "application/xhtml+xml", "text/plain")
        ):
            return make_error(
                f"Unsupported content-type: {content_type}",
                final_url,
                status_code=status_code,
                status_text=status_text,
            )

        # Read content with size limit (raw bytes cap to prevent memory issues)
        max_bytes = 500000  # 500KB raw cap
        content_bytes = b""
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                content_bytes += chunk
                if len(content_bytes) > max_bytes:
                    break

        encoding = response.encoding or "utf-8"
        html_text = content_bytes.decode(encoding, errors="replace")

        # === Extract title (needed for both modes) ===
        title = ""
        try:
            meta = trafilatura.metadata.extract_metadata(content_bytes, url=final_url)
            if meta and getattr(meta, "title", None):
                title = meta.title.strip()
        except Exception:
            pass

        if not title:
            try:
                soup_title = BeautifulSoup(html_text[:5000], "lxml")
                if soup_title.title and soup_title.title.string:
                    title = soup_title.title.string.strip()
            except Exception:
                pass

        # === Title mode: return just the title ===
        if fetch_mode == "title":
            return make_result(final_url, title, "", 0, status_code, status_text)

        # === Full mode: extract content ===
        content_md = ""
        min_content_length = 200

        try:
            content_md = (
                trafilatura.extract(
                    content_bytes,
                    url=final_url,
                    include_comments=False,
                    include_tables=True,
                    output_format="markdown",
                )
                or ""
            )
        except Exception:
            pass

        # Fallback to BeautifulSoup
        if not content_md or len(content_md) < min_content_length:
            try:
                soup = BeautifulSoup(html_text, "lxml")

                for tag in soup(
                    ["script", "style", "noscript", "nav", "footer", "header"]
                ):
                    tag.decompose()

                text = soup.get_text("\n")
                text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
                bs_content = text.strip()

                if len(bs_content) > len(content_md or ""):
                    content_md = bs_content
            except Exception:
                pass

        # === Jina Reader API Fallback ===
        if use_jina_fallback and (
            not content_md or len(content_md) < min_content_length
        ):
            try:
                jina_url = f"https://r.jina.ai/{url}"
                jina_headers = {
                    "Accept": "text/plain",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                }
                jina_response = requests.get(
                    jina_url, headers=jina_headers, timeout=timeout
                )

                if jina_response.status_code == 200:
                    jina_content = jina_response.text.strip()
                    if jina_content and len(jina_content) > min_content_length:
                        content_md = jina_content

                        if not title:
                            title_match = re.match(r"^#\s*(.+?)[\n\r]", jina_content)
                            if title_match:
                                title = title_match.group(1).strip()
            except Exception:
                pass

        # === Clean content ===
        if content_md:
            content_md = re.sub(r"\n{4,}", "\n\n\n", content_md)
            content_md = content_md.strip()

        if not content_md:
            return make_result(
                final_url,
                title,
                "",
                0,
                status_code,
                status_text,
                message="No content could be extracted. Site may require JavaScript rendering — use browser tools (Playwright) instead.",
            )

        total_content_length = len(content_md)

        # === Truncation + file save ===
        was_truncated = False
        content_file = None

        if not unlimited and total_content_length > max_content_length:
            content_file = save_content_file(content_md, final_url, session_id)

            truncated = content_md[:max_content_length]
            last_period = truncated.rfind(".")
            if last_period > max_content_length * 0.8:
                truncated = truncated[: last_period + 1]
            content_md = truncated
            was_truncated = True

        # === Build message ===
        message = ""
        if was_truncated:
            message = (
                f"Content truncated to {len(content_md)} chars. "
                f"Full content ({total_content_length} chars) saved to content_file. "
                f"Use grep_files(pattern, path=content_file) to search for specific info, "
                f"or read_file(file_path=content_file, offset=N, limit=M) to paginate."
            )

        return make_result(
            final_url,
            title,
            content_md,
            total_content_length,
            status_code,
            status_text,
            was_truncated=was_truncated,
            content_file=content_file,
            message=message,
        )

    except Exception as e:
        sc, st = 0, ""
        if hasattr(e, "response") and e.response is not None:
            sc = e.response.status_code
            st = e.response.reason or ""

        error_type = type(e).__name__
        if "Timeout" in error_type:
            msg = catalog_make_error("CONNECTION_TIMEOUT", target=url).message
        elif "ConnectionError" in error_type:
            msg = catalog_make_error(
                "CONNECTION_FAILED", target=url, detail=str(e)
            ).message
        elif "HTTPError" in error_type:
            msg = f"HTTP error: {str(e)}"
        else:
            msg = f"Fetch failed: {str(e)}"

        return make_error(msg, url, status_code=sc, status_text=st)
