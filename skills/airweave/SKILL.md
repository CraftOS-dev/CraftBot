---
name: airweave
description: Context retrieval layer for AI agents across users' applications. Search and retrieve context from Airweave collections. Airweave indexes and syncs data from user applications to enable optimal context retrieval by AI agents. Supports semantic, keyword, and agentic search. Use when users ask about their data in connected apps (Slack, GitHub, Notion, Jira, Confluence, Google Drive, Salesforce, Linear, SharePoint, Stripe, etc.), need to find documents or information from their workspace, want answers based on their company data, or need you to check app data for context to complete a task.
metadata: {"clawdbot":{"requires":{"bins":["python3"],"env":["AIRWEAVE_API_KEY","AIRWEAVE_COLLECTION_ID"]},"primaryEnv":"AIRWEAVE_API_KEY"}}
---

# Airweave Search

Search and retrieve context from Airweave collections using the search script at `{baseDir}/scripts/search.py`.

## When to Search

**Search when the user:**
- Asks about data in their connected apps ("What did we discuss in Slack about...")
- Needs to find documents, messages, issues, or records
- Asks factual questions about their workspace ("Who is responsible for...", "What's our policy on...")
- References specific tools by name ("in Notion", "on GitHub", "in Jira")
- Needs recent information you don't have in your training
- Needs you to check app data for context ("check our Notion docs", "look at the Jira ticket")

**Don't search when:**
- User asks general knowledge questions (use your training)
- User already provided all needed context in the conversation
- The question is about Airweave itself, not data within it

## Query Formulation

Turn user intent into effective search queries:

| User Says | Search Query |
|-----------|--------------|
| "What did Sarah say about the launch?" | "Sarah product launch" |
| "Find the API documentation" | "API documentation" |
| "Any bugs reported this week?" | "bug report issues" |
| "What's our refund policy?" | "refund policy customer" |

**Tips:**
- Use natural language — Airweave uses semantic search
- Include context — "pricing feedback" beats just "pricing"
- Be specific but not too narrow
- Skip filler words like "please find", "can you search for"

## Running a Search

Execute the search script:

```bash
python3 {baseDir}/scripts/search.py "your search query"
```

**Optional parameters:**
- `--limit N` — Max results (default: 20)
- `--temporal N` — Temporal relevance 0-1 (default: 0, use 0.7+ for "recent", "latest")
- `--strategy TYPE` — Retrieval strategy: hybrid, semantic, keyword (default: hybrid)
- `--raw` — Return raw results instead of AI-generated answer
- `--expand` — Enable query expansion for broader results
- `--rerank / --no-rerank` — Toggle LLM reranking (default: on)

**Examples:**

```bash
# Basic search
python3 {baseDir}/scripts/search.py "customer feedback pricing"

# Recent conversations
python3 {baseDir}/scripts/search.py "product launch updates" --temporal 0.8

# Find specific document
python3 {baseDir}/scripts/search.py "API authentication docs" --strategy keyword

# Get raw results for exploration
python3 {baseDir}/scripts/search.py "project status" --limit 30 --raw

# Broad search with query expansion
python3 {baseDir}/scripts/search.py "onboarding" --expand
```

## Handling Results

**Interpreting scores:**
- 0.85+ → Highly relevant, use confidently
- 0.70-0.85 → Likely relevant, use with context
- 0.50-0.70 → Possibly relevant, mention uncertainty
- Below 0.50 → Weak match, consider rephrasing

**Presenting to users:**
1. Lead with the answer — don't start with "I found 5 results"
2. Cite sources — mention where info came from ("According to your Slack conversation...")
3. Synthesize — combine relevant parts into a coherent response
4. Acknowledge gaps — if results don't fully answer, say so

## Handling No Results

If search returns nothing useful:
1. Broaden the query — remove specific terms
2. Try different phrasing — use synonyms
3. Increase limit — fetch more results
4. Ask for clarification — user might have more context

## Parameter Reference

See [PARAMETERS.md](references/PARAMETERS.md) for detailed parameter guidance.

## Examples

See [EXAMPLES.md](references/EXAMPLES.md) for complete search scenarios.
