---
name: reddit-api
description: "Reddit Search — Search posts, comments, users, and subreddits across 100M+ indexed Reddit entries. Find discussions, track topics, discover communities, and analyze engagement. No Reddit API key needed — works through Xpoz MCP with natural language queries."
homepage: https://xpoz.ai
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["mcporter"], "skills": ["xpoz-setup"], "network": ["mcp.xpoz.ai"], "credentials": "Xpoz account (free tier) — auth via xpoz-setup skill (OAuth 2.1)" },
        "install": [{"id": "node", "kind": "node", "package": "mcporter", "bins": ["mcporter"], "label": "Install mcporter (npm)"}],
      },
  }
tags:
  - reddit
  - reddit-search
  - reddit-api
  - subreddit
  - reddit-comments
  - reddit-posts
  - community
  - discussion
  - social-media
  - mcp
  - xpoz
  - research
---

# Reddit Search

**Search 100M+ Reddit posts and comments without a Reddit API key.**

Find discussions, discover subreddits, look up users, and export results — all through Xpoz MCP. No Reddit API credentials needed, no rate limit headaches, no OAuth setup with Reddit.

---

## ⚡ Setup

👉 **Follow [`xpoz-setup`](https://clawhub.ai/skills/xpoz-setup)** — handles auth automatically. User just clicks "Authorize" once.

---

## Setup

Run `xpoz-setup` skill. Verify: `mcporter call xpoz.checkAccessKeyStatus`

## What You Can Search

| Tool | What It Does |
|------|-------------|
| `getRedditPostsByKeywords` | Search posts by topic |
| `getRedditCommentsByKeywords` | Search comments (where deep expertise lives) |
| `getRedditUsersByKeywords` | Find users discussing a topic |
| `getRedditSubredditsByKeywords` | Discover relevant communities |
| `getRedditPostsByAuthor` | Get a user's post history |
| `getRedditUser` | Look up a specific profile |
| `searchRedditUsers` | Find users by name |

---

## Quick Examples

### Search Posts

```bash
mcporter call xpoz.getRedditPostsByKeywords \
  query="self hosting AND docker" \
  startDate=2026-01-01 \
  limit=100

# Always poll for results:
mcporter call xpoz.checkOperationStatus operationId=op_abc123
```

### Search Comments

Comments often contain the deepest expertise — practitioners sharing real experience:

```bash
mcporter call xpoz.getRedditCommentsByKeywords \
  query="kubernetes networking troubleshoot" \
  fields='["id","text","authorUsername","subredditName","score","createdAtDate"]'
```

### Find Subreddits

```bash
mcporter call xpoz.getRedditSubredditsByKeywords \
  query="machine learning" \
  limit=30
```

### Look Up a User

```bash
mcporter call xpoz.getRedditUser \
  identifier=spez \
  identifierType=username
```

---

## Boolean Queries

- `AND`, `OR`, `NOT` (uppercase)
- `"exact phrase"` for precise matching
- `()` for grouping

```bash
mcporter call xpoz.getRedditPostsByKeywords \
  query="(python OR rust) AND \"web scraping\" NOT selenium"
```

---

## CSV Export

Every search returns a `dataDumpExportOperationId`. Poll it to get a download URL with the full dataset (up to 64K rows):

```bash
mcporter call xpoz.checkOperationStatus operationId=op_datadump_xyz
# → result.url = S3 download link
```

---

## Why Not Use the Reddit API Directly?

| | Reddit API | Xpoz Reddit Search |
|--|-----------|-------------------|
| **Auth** | OAuth + client ID + secret | One-click Xpoz auth |
| **Rate limits** | 100 requests/min | Handled automatically |
| **Search quality** | Reddit's search is notoriously poor | Full-text indexed, boolean operators |
| **Comments** | No keyword search for comments | ✅ Full comment search |
| **Export** | Manual pagination | One-click CSV (64K rows) |
| **Historical** | Limited | Back to 2019 |

---

## Related Skills

- **[xpoz-social-search](https://clawhub.ai/skills/xpoz-social-search)** — Cross-platform search (Twitter + Instagram + Reddit)
- **[expert-finder](https://clawhub.ai/skills/expert-finder)** — Find domain experts from social data
- **[social-sentiment](https://clawhub.ai/skills/social-sentiment)** — Brand sentiment analysis

---

**Website:** [xpoz.ai](https://xpoz.ai) • **Free tier available** • No Reddit API key needed

Built for ClawHub • 2026
