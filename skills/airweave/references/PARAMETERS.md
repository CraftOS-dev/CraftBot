# Airweave Search Parameters

Detailed guide for search parameters and when to use them.

## Core Parameters

### `--limit N`
Maximum number of results to return (default: 20).

| Value | Use Case |
|-------|----------|
| 5-10 | Quick answers, direct questions |
| 15-25 | Exploration, "show me everything about X" |
| 50+ | Comprehensive research, audits |

### `--temporal N`
Temporal relevance bias from 0 (ignore time) to 1 (strongly prefer recent).

| Value | Use Case |
|-------|----------|
| 0 | Default. No time preference. |
| 0.3-0.5 | Slight preference for recent |
| 0.6-0.8 | Prefer recent, "recent updates on X" |
| 0.9-1.0 | Strongly recent, "what happened this week", "latest" |

**Trigger words for high temporal:**
- "recent", "latest", "this week", "today", "yesterday"
- "just", "new", "current", "now"

### `--strategy TYPE`
Retrieval strategy to use.

| Strategy | Best For |
|----------|----------|
| `hybrid` | Default. Combines semantic + keyword. Good for most queries. |
| `semantic` | Conceptual/semantic queries. "Things similar to X", fuzzy matching. |
| `keyword` | Exact terms, names, IDs, error codes. When precision matters. |

**Use `keyword` when:**
- Searching for specific names, IDs, or codes
- User quoted exact text: `"error 404"`
- Technical identifiers: `JIRA-1234`, `PR #567`

**Use `semantic` when:**
- Conceptual questions: "how do we handle refunds"
- Fuzzy matching: "stuff like the marketing campaign"
- No specific keywords in mind

### `--raw`
Return raw results instead of AI-generated answer.

**Use raw when:**
- User wants to browse/explore results themselves
- You need to see all sources before synthesizing
- Debugging search quality
- User says "show me the results" or "what did you find"

**Use completion (default) when:**
- User wants a direct answer
- Summarization is helpful
- Quick factual questions

## Modifier Flags

### `--rerank` / `--no-rerank`
LLM-based reranking for improved relevance.

- **With reranking (default):** Better relevance, slightly slower
- **Without reranking:** Faster, useful for large result sets

### `--expand` / `--no-expand`
Query expansion generates variations of the query.

- **Without expansion (default):** More precise, use for exact matches
- **With expansion:** Better recall, finds related terms

### `--filters`
Enable filter interpretation (extracts filters from natural language).

- **Without filters (default):** Query used as-is
- **With filters:** Parses things like "from last week" or "in #engineering"

### `--offset N`
Pagination offset for results (default: 0).

### `--json`
Output raw JSON response. Useful for debugging or piping to other tools.

## Parameter Combinations

### Quick Direct Answer
```bash
python3 search.py "what is our refund policy" --limit 5
```

### Recent Activity
```bash
python3 search.py "product launch updates" --temporal 0.8 --limit 15
```

### Find Specific Document
```bash
python3 search.py "API authentication documentation" --strategy keyword
```

### Comprehensive Research
```bash
python3 search.py "customer feedback" --limit 30 --raw
```

### Exact Match Search
```bash
python3 search.py "ENG-1234" --strategy keyword --no-rerank
```

### Broad Exploration with Query Expansion
```bash
python3 search.py "onboarding process" --expand --limit 25
```
