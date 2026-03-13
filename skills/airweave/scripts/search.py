#!/usr/bin/env python3
"""
Airweave Search Script for Clawdbot

Searches an Airweave collection and returns results.

Environment variables required:
  AIRWEAVE_API_KEY        - Your Airweave API key
  AIRWEAVE_COLLECTION_ID  - The readable_id of your collection

Optional:
  AIRWEAVE_BASE_URL       - API base URL (default: https://api.airweave.ai)

Usage:
  python3 search.py "your search query" [options]

Options:
  --limit N        Max results (default: 20)
  --offset N       Pagination offset (default: 0)
  --temporal N     Temporal relevance 0-1 (default: 0)
  --strategy TYPE  Retrieval strategy: hybrid, semantic, keyword (default: hybrid)
  --raw            Return raw results instead of generated answer
  --rerank         Enable reranking (default: true)
  --no-rerank      Disable reranking
  --expand         Enable query expansion (default: false)
  --no-expand      Disable query expansion
  --filters        Enable filter interpretation
"""

import argparse
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def get_env(name: str, default: str = None) -> str:
    """Get environment variable or exit with error."""
    value = os.environ.get(name, default)
    if value is None:
        print(f"Error: {name} environment variable is required", file=sys.stderr)
        sys.exit(1)
    return value


def search(
    query: str,
    api_key: str,
    collection_id: str,
    base_url: str = "https://api.airweave.ai",
    limit: int = 10,
    temporal_relevance: float = 0,
    retrieval_strategy: str = "hybrid",
    generate_answer: bool = True,
    rerank: bool = True,
    expand_query: bool = False,
    interpret_filters: bool = False,
    offset: int = 0,
) -> dict:
    """Execute search against Airweave API."""
    
    url = f"{base_url}/collections/{collection_id}/search"
    
    payload = {
        "query": query,
        "limit": limit,
        "offset": offset,
        "retrieval_strategy": retrieval_strategy,
        "temporal_relevance": temporal_relevance,
        "generate_answer": generate_answer,
        "rerank": rerank,
        "expand_query": expand_query,
        "interpret_filters": interpret_filters,
    }
    
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    
    req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        print(f"API Error ({e.code}): {error_body}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Connection Error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def format_results(response: dict, raw: bool = False) -> str:
    """Format search results for display."""
    output = []
    
    # If completion response, show the generated answer first
    if not raw and response.get("completion"):
        output.append("## Answer\n")
        output.append(response["completion"])
        output.append("\n")
    
    # Show individual results
    results = response.get("results", [])
    if results:
        output.append(f"\n## Sources ({len(results)} results)\n")
        for i, result in enumerate(results, 1):
            score = result.get("score", 0)
            
            # Get source from system_metadata
            system_meta = result.get("system_metadata", {})
            source = system_meta.get("source_name", "Unknown")
            
            # Get title from name or source_fields
            title = result.get("name", "Untitled")
            source_fields = result.get("source_fields", {})
            if source_fields.get("filename"):
                title = source_fields["filename"]
            
            # Get content from textual_representation
            content = result.get("textual_representation", "")
            
            # Get URL from source_fields
            url = source_fields.get("web_url", "")
            
            # Truncate content for display
            if len(content) > 500:
                content = content[:500] + "..."
            
            output.append(f"### {i}. {title}")
            output.append(f"**Source:** {source} | **Score:** {score:.2f}")
            if url:
                output.append(f"**URL:** {url}")
            output.append(f"\n{content}\n")
    elif not response.get("completion"):
        output.append("No results found. Try broadening your search query.")
    
    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="Search an Airweave collection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("--offset", type=int, default=0, help="Result offset for pagination (default: 0)")
    parser.add_argument("--temporal", type=float, default=0, help="Temporal relevance 0-1 (default: 0, use higher for recent)")
    parser.add_argument("--strategy", choices=["hybrid", "semantic", "keyword"], default="hybrid", help="Retrieval strategy")
    parser.add_argument("--raw", action="store_true", help="Return raw results instead of generated answer")
    parser.add_argument("--rerank", action="store_true", default=True, help="Enable reranking (default)")
    parser.add_argument("--no-rerank", action="store_false", dest="rerank", help="Disable reranking")
    parser.add_argument("--expand", action="store_true", default=False, help="Enable query expansion")
    parser.add_argument("--no-expand", action="store_false", dest="expand", help="Disable query expansion (default)")
    parser.add_argument("--filters", action="store_true", default=False, help="Enable filter interpretation")
    parser.add_argument("--json", action="store_true", help="Output raw JSON response")
    
    args = parser.parse_args()
    
    # Get configuration from environment
    api_key = get_env("AIRWEAVE_API_KEY")
    collection_id = get_env("AIRWEAVE_COLLECTION_ID")
    base_url = get_env("AIRWEAVE_BASE_URL", "https://api.airweave.ai")
    
    # Execute search
    response = search(
        query=args.query,
        api_key=api_key,
        collection_id=collection_id,
        base_url=base_url,
        limit=args.limit,
        offset=args.offset,
        temporal_relevance=args.temporal,
        retrieval_strategy=args.strategy,
        generate_answer=not args.raw,
        rerank=args.rerank,
        expand_query=args.expand,
        interpret_filters=args.filters,
    )
    
    # Output results
    if args.json:
        print(json.dumps(response, indent=2))
    else:
        print(format_results(response, raw=args.raw))


if __name__ == "__main__":
    main()
