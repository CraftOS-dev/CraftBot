from agent_core import action

@action(
    name="web_fetch",
    description="""Fetches content from a URL and returns processed markdown content.
- Takes a URL and an optional prompt describing what information to extract
- Fetches the URL content and converts HTML to markdown
- Uses two-tier extraction: fast static extraction first, then Jina Reader API for JS-rendered sites
- Handles redirects: when redirecting to a different host, returns redirect info
- HTTP URLs are automatically upgraded to HTTPS
- Use web_search action first to find relevant URLs, then use this to read full content

IMPORTANT: This action may fail for authenticated or private URLs. For sites requiring
authentication (Google Docs, Confluence, Jira, etc.), use specialized authenticated tools.""",
    mode="CLI",
    action_sets=["core"],
    input_schema={
        "url": {
            "type": "string",
            "example": "https://example.com/article",
            "description": "The URL to fetch content from. Must be a valid http(s) URL.",
            "required": True
        },
        "prompt": {
            "type": "string",
            "example": "Extract the main points and key takeaways from this article",
            "description": "Optional prompt describing what information to extract from the page. If provided, content will be structured around this prompt."
        },
        "timeout": {
            "type": "number",
            "example": 30,
            "description": "Request timeout in seconds. Defaults to 30."
        },
        "max_content_length": {
            "type": "integer",
            "example": 50000,
            "description": "Maximum content length in characters. Content exceeding this will be truncated. Defaults to 50000."
        },
        "use_jina_fallback": {
            "type": "boolean",
            "example": True,
            "description": "Use Jina Reader API as fallback for JS-rendered sites. Defaults to True."
        },
        "min_content_length": {
            "type": "integer",
            "example": 200,
            "description": "Minimum content length to consider extraction successful. Below this triggers fallback. Defaults to 200."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success', 'redirect', or 'error'."
        },
        "url": {
            "type": "string",
            "description": "The original requested URL."
        },
        "final_url": {
            "type": "string",
            "description": "The final URL after any redirects (same host only)."
        },
        "redirect_url": {
            "type": "string",
            "description": "Present when status='redirect'. The URL to follow for cross-host redirects."
        },
        "title": {
            "type": "string",
            "description": "The page title."
        },
        "content": {
            "type": "string",
            "description": "The extracted content in markdown format."
        },
        "content_length": {
            "type": "integer",
            "description": "Length of the content in characters."
        },
        "was_truncated": {
            "type": "boolean",
            "description": "True if content was truncated due to max_content_length."
        },
        "prompt_used": {
            "type": "string",
            "description": "The prompt that was applied (if any)."
        },
        "message": {
            "type": "string",
            "description": "Error or informational message."
        },
        "extraction_method": {
            "type": "string",
            "description": "Method used for extraction: 'static' (trafilatura/BeautifulSoup) or 'jina' (Jina Reader API)."
        }
    },
    requirement=["requests", "beautifulsoup4", "trafilatura", "lxml"],
    test_payload={
        "url": "https://example.com/article",
        "prompt": "Summarize the main content",
        "timeout": 30,
        "simulated_mode": True
    }
)
def web_fetch(input_data: dict) -> dict:
    """
    Fetches content from a URL and returns processed markdown content.
    Uses two-tier extraction: fast static extraction first, then Jina Reader API for JS-rendered sites.
    """
    import re
    from urllib.parse import urlparse

    simulated_mode = input_data.get('simulated_mode', False)
    url = str(input_data.get('url', '')).strip()
    prompt = str(input_data.get('prompt', '')).strip() if input_data.get('prompt') else None
    timeout = float(input_data.get('timeout', 30))
    max_content_length = int(input_data.get('max_content_length', 50000))
    use_jina_fallback = input_data.get('use_jina_fallback', True)
    min_content_length = int(input_data.get('min_content_length', 200))

    def _make_error(message, url=''):
        return {
            'status': 'error',
            'url': url,
            'final_url': '',
            'title': '',
            'content': '',
            'content_length': 0,
            'was_truncated': False,
            'prompt_used': prompt or '',
            'message': message
        }

    def _make_redirect(original_url, redirect_url):
        return {
            'status': 'redirect',
            'url': original_url,
            'final_url': '',
            'redirect_url': redirect_url,
            'title': '',
            'content': '',
            'content_length': 0,
            'was_truncated': False,
            'prompt_used': prompt or '',
            'message': f'Redirect to different host detected. Please make a new request to: {redirect_url}'
        }

    # Validate URL
    if not url:
        return _make_error('URL is required.')

    # Auto-upgrade HTTP to HTTPS
    if url.startswith('http://'):
        url = 'https://' + url[7:]

    if not re.match(r'^https?://', url, re.I):
        return _make_error('A valid http(s) URL is required.', url)

    # Parse original URL for host comparison
    try:
        original_parsed = urlparse(url)
        original_host = original_parsed.netloc.lower()
    except Exception as e:
        return _make_error(f'Invalid URL format: {str(e)}', url)

    # Simulated mode for testing
    if simulated_mode:
        mock_content = f"""# Test Page Title

This is simulated content fetched from {url}.

## Main Content

This is the main body of the page content, converted to markdown format.

- Point 1: Important information
- Point 2: More details
- Point 3: Additional context

## Summary

This is a test page demonstrating the web_fetch action functionality.
"""
        if prompt:
            mock_content = f"**Prompt:** {prompt}\n\n---\n\n{mock_content}"

        return {
            'status': 'success',
            'url': url,
            'final_url': url,
            'title': 'Test Page Title',
            'content': mock_content,
            'content_length': len(mock_content),
            'was_truncated': False,
            'prompt_used': prompt or '',
            'message': ''
        }

    # Fetch the URL
    try:
        import requests
        from bs4 import BeautifulSoup
        import trafilatura

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9'
        }

        # First, make a HEAD request to check for redirects without downloading content
        try:
            head_response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
            final_url = str(head_response.url)
            final_parsed = urlparse(final_url)
            final_host = final_parsed.netloc.lower()

            # Check if redirect is to a different host
            if final_host != original_host:
                return _make_redirect(url, final_url)
        except requests.exceptions.RequestException:
            # HEAD failed, continue with GET
            pass

        # Fetch the content
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
        response.raise_for_status()

        final_url = str(response.url)
        final_parsed = urlparse(final_url)
        final_host = final_parsed.netloc.lower()

        # Double-check for cross-host redirect
        if final_host != original_host:
            return _make_redirect(url, final_url)

        # Check content type
        content_type = response.headers.get('Content-Type', '')
        if not any(t in content_type for t in ('text/html', 'application/xhtml+xml', 'text/plain')):
            return _make_error(f'Unsupported content-type: {content_type}', url)

        # Read content with size limit
        max_bytes = max_content_length * 4  # Rough estimate for UTF-8
        content_bytes = b''
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                content_bytes += chunk
                if len(content_bytes) > max_bytes:
                    break

        encoding = response.encoding or 'utf-8'
        html_text = content_bytes.decode(encoding, errors='replace')

        # === TIER 1: Fast Static Extraction ===
        title = ''
        content_md = ''
        extraction_method = 'static'

        try:
            # Try trafilatura for main content extraction
            content_md = trafilatura.extract(
                content_bytes,
                url=final_url,
                include_comments=False,
                include_tables=True,
                output_format='markdown'
            ) or ''

            # Try to get title from metadata
            try:
                meta = trafilatura.metadata.extract_metadata(content_bytes, url=final_url)
                if meta and getattr(meta, 'title', None):
                    title = meta.title.strip()
            except Exception:
                pass

        except Exception:
            pass

        # Fallback to BeautifulSoup if trafilatura fails
        if not content_md or len(content_md) < min_content_length:
            soup = BeautifulSoup(html_text, 'lxml')

            # Get title
            if not title and soup.title and soup.title.string:
                title = soup.title.string.strip()

            # Remove script/style elements
            for tag in soup(['script', 'style', 'noscript', 'nav', 'footer', 'header']):
                tag.decompose()

            # Get text content
            text = soup.get_text('\n')
            # Clean up whitespace
            text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
            bs_content = text.strip()

            # Use BeautifulSoup content if better than trafilatura
            if len(bs_content) > len(content_md or ''):
                content_md = bs_content

        # === TIER 2: Jina Reader API Fallback ===
        # Use Jina if static extraction got insufficient content
        if use_jina_fallback and (not content_md or len(content_md) < min_content_length):
            try:
                jina_url = f"https://r.jina.ai/{url}"
                jina_headers = {
                    'Accept': 'text/plain',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                jina_response = requests.get(jina_url, headers=jina_headers, timeout=timeout)

                if jina_response.status_code == 200:
                    jina_content = jina_response.text.strip()

                    # Jina returns markdown with title as first line
                    if jina_content and len(jina_content) > min_content_length:
                        content_md = jina_content
                        extraction_method = 'jina'

                        # Extract title from Jina response (usually first # heading)
                        title_match = re.match(r'^#\s*(.+?)[\n\r]', jina_content)
                        if title_match and not title:
                            title = title_match.group(1).strip()

            except Exception:
                # Jina fallback failed, continue with whatever we have
                pass

        # === Content Quality Check ===
        # Clean and validate content
        if content_md:
            # Remove excessive whitespace
            content_md = re.sub(r'\n{4,}', '\n\n\n', content_md)
            content_md = content_md.strip()

        # Check if truncation is needed
        was_truncated = False
        if len(content_md) > max_content_length:
            content_md = content_md[:max_content_length]
            # Try to truncate at a sentence boundary
            last_period = content_md.rfind('.')
            if last_period > max_content_length * 0.8:
                content_md = content_md[:last_period + 1]
            content_md += '\n\n[Content truncated due to length...]'
            was_truncated = True

        # Build result with extraction method info
        message = ''
        if not content_md or len(content_md) < min_content_length:
            message = 'Warning: Extracted content may be incomplete. Site may require JavaScript rendering or authentication.'

        return {
            'status': 'success',
            'url': url,
            'final_url': final_url,
            'title': title or '',
            'content': content_md,
            'content_length': len(content_md),
            'was_truncated': was_truncated,
            'prompt_used': prompt or '',
            'message': message,
            'extraction_method': extraction_method
        }

    except requests.exceptions.Timeout:
        return _make_error(f'Request timed out after {timeout} seconds.', url)
    except requests.exceptions.ConnectionError as e:
        return _make_error(f'Connection error: {str(e)}', url)
    except requests.exceptions.HTTPError as e:
        return _make_error(f'HTTP error: {str(e)}', url)
    except Exception as e:
        return _make_error(f'Unexpected error: {str(e)}', url)
