from agent_core import action

@action(
    name="web_search",
    description="""Performs web search and returns search result snippets with markdown hyperlinks.
- Uses Google Custom Search API (if credentials exist) or DuckDuckGo fallback
- Returns search result blocks with title, URL, and content snippets
- Results are formatted with markdown links for easy reference
- Use web_fetch action to read full page content from specific URLs""",
    default=True,
    mode="CLI",
    action_sets=["core"],
    input_schema={
        "query": {
            "type": "string",
            "example": "latest AI developments 2025",
            "description": "The search query to use. Must be at least 2 characters.",
            "required": True
        },
        "num_results": {
            "type": "integer",
            "example": 5,
            "description": "Number of results to return (1-20). Defaults to 5."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'."
        },
        "results": {
            "type": "array",
            "description": "List of search results, each containing: title, url, snippet, markdown_link."
        },
        "sources_markdown": {
            "type": "string",
            "description": "Pre-formatted markdown list of sources for easy inclusion in responses."
        },
        "result_count": {
            "type": "integer",
            "description": "Number of results returned."
        },
        "message": {
            "type": "string",
            "description": "Error message if status is 'error'."
        }
    },
    requirement=["ddgs", "google-api-python-client"],
    test_payload={
        "query": "latest AI developments 2025",
        "num_results": 5,
        "simulated_mode": True
    }
)
def web_search(input_data: dict) -> dict:
    """
    Web search action that returns search result snippets with markdown hyperlinks.
    Similar to Claude Code's WebSearch tool - returns snippets, not full page content.
    """
    import os
    import re

    simulated_mode = input_data.get('simulated_mode', False)
    query = input_data.get('query', '').strip()
    num_results = min(max(int(input_data.get('num_results', 5)), 1), 20)

    # Validate query
    if not query or len(query) < 2:
        return {
            'status': 'error',
            'message': 'Query is required and must be at least 2 characters.',
            'results': [],
            'sources_markdown': '',
            'result_count': 0
        }

    def _normalise_ws(text):
        """Normalize whitespace in text."""
        return re.sub(r'\s+', ' ', (text or '')).strip()

    def _format_results(raw_results):
        """Format raw search results into standardized output."""
        formatted = []
        for r in raw_results:
            title = _normalise_ws(r.get('title', 'Untitled'))
            url = r.get('url', '')
            snippet = _normalise_ws(r.get('snippet', r.get('content', r.get('description', ''))))

            formatted.append({
                'title': title,
                'url': url,
                'snippet': snippet,
                'markdown_link': f"[{title}]({url})"
            })
        return formatted

    def _generate_sources_markdown(results):
        """Generate a markdown-formatted sources list."""
        if not results:
            return ''
        lines = ['Sources:']
        for r in results:
            lines.append(f"- [{r['title']}]({r['url']})")
        return '\n'.join(lines)

    # Simulated mode for testing
    if simulated_mode:
        mock_results = [
            {
                'title': f'Test Result {i+1}: {query}',
                'url': f'https://example.com/result{i+1}',
                'snippet': f'This is a test snippet for result {i+1} about {query}.',
                'markdown_link': f'[Test Result {i+1}: {query}](https://example.com/result{i+1})'
            }
            for i in range(num_results)
        ]
        return {
            'status': 'success',
            'results': mock_results,
            'sources_markdown': _generate_sources_markdown(mock_results),
            'result_count': len(mock_results),
            'message': ''
        }

    # Real search implementation
    def duckduckgo_search(q, n=5):
        """Search using DuckDuckGo via ddgs package."""
        from ddgs import DDGS
        results = []
        try:
            ddgs = DDGS()
            hits = list(ddgs.text(q, max_results=n + 10))  # Get extra for filtering
            for hit in hits:
                url = hit.get('href') or hit.get('url', '')
                results.append({
                    'title': hit.get('title', 'Untitled'),
                    'url': url,
                    'snippet': hit.get('body', hit.get('description', ''))
                })
        except Exception as e:
            raise Exception(f"DuckDuckGo search failed: {str(e)}")
        return results

    def google_cse_search(q, n=5):
        """Search using Google Custom Search API."""
        try:
            from googleapiclient.discovery import build
            api_key = os.getenv('GOOGLE_API_KEY')
            cse_id = os.getenv('GOOGLE_CSE_ID')
            if not api_key or not cse_id:
                raise Exception('No Google API credentials')

            service = build('customsearch', 'v1', developerKey=api_key)
            res = service.cse().list(q=q, cx=cse_id, num=min(n + 5, 10)).execute()
            items = res.get('items', [])

            return [{
                'title': item.get('title', 'Untitled'),
                'url': item.get('link', ''),
                'snippet': item.get('snippet', '')
            } for item in items]
        except Exception:
            # Fallback to DuckDuckGo
            return duckduckgo_search(q, n)

    try:
        # Try Google first, fallback to DuckDuckGo
        raw_results = google_cse_search(query, num_results)

        # Limit to requested number
        raw_results = raw_results[:num_results]

        # Format results
        formatted_results = _format_results(raw_results)

        return {
            'status': 'success',
            'results': formatted_results,
            'sources_markdown': _generate_sources_markdown(formatted_results),
            'result_count': len(formatted_results),
            'message': ''
        }

    except Exception as e:
        return {
            'status': 'error',
            'message': str(e),
            'results': [],
            'sources_markdown': '',
            'result_count': 0
        }
