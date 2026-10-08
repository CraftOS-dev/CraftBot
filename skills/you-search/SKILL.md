---
name: you-search
description: Web search via You.com's MCP search tool. Keyless by default — no API key needed. Use for live information, current events, documentation lookups, or research queries.
homepage: https://you.com
metadata: {"clawdbot":{"emoji":"🔍","requires":{"bins":["node"]},"primaryEnv":"YDC_API_KEY"}}
---

# You.com Search

Web search using You.com's hosted MCP endpoint. Keyless by default via the free profile — works with no API key and no signup.

## Search

```bash
node {baseDir}/scripts/search.mjs "query"
node {baseDir}/scripts/search.mjs "query" -n 10
```

## Options

- `-n <count>`: Number of results (default: 5, max: 20)

## Setup

None needed — the free profile endpoint (`https://api.you.com/mcp?profile=free`) requires no key.

To use the authenticated endpoint instead (full You.com toolset):

```bash
export YDC_API_KEY="your-key"   # optional, from https://you.com/platform/api-keys
```

## Output Format

```
## Sources

- **Result Title**
  https://example.com/page
  Snippet from the search result...

- **Result Title**
  ...
```

## Notes

- Requires Node 18+ (uses global fetch)
- Zero npm dependencies — plain HTTP JSON-RPC against the You.com MCP endpoint
- Authenticated mode is a drop-in: setting `YDC_API_KEY` switches the endpoint, same usage
- Exits non-zero with a clear error message if the endpoint is unreachable or the query fails
