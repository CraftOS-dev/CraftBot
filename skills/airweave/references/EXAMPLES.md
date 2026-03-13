# Airweave Search Examples

Real-world search scenarios and how to handle them.

## Example 1: Finding Recent Discussions

**User:** "What did the team discuss about the product launch in Slack?"

**Reasoning:**
- Asking about Slack conversations → search Airweave
- "Recent" implied by context → moderate recency bias
- Wants discussion summary → use completion

**Search:**
```bash
python3 search.py "team product launch discussion" --recency 0.6 --limit 10
```

**Response pattern:**
> Based on recent Slack conversations, the team discussed [summary]...
> 
> Key points mentioned:
> - [Point 1] (from #channel on date)
> - [Point 2] (from #channel on date)

---

## Example 2: Finding Documentation

**User:** "Where's our API documentation for authentication?"

**Reasoning:**
- Looking for specific docs → search
- "Documentation" is concrete → hybrid or keyword
- Wants location/link → include URL in response

**Search:**
```bash
python3 search.py "API authentication documentation" --method hybrid --limit 5
```

**Response pattern:**
> Your API authentication docs are in [location]. Here's the key info:
> [Summary of auth approach]
> 
> Full docs: [URL]

---

## Example 3: Recent Activity Check

**User:** "Any bugs reported this week?"

**Reasoning:**
- "This week" → high recency bias
- "Bugs" likely in issue tracker → search
- Wants list → maybe use raw for completeness

**Search:**
```bash
python3 search.py "bug report issue" --recency 0.9 --limit 20 --raw
```

**Response pattern:**
> I found [N] bug reports from this week:
> 
> 1. **[Title]** - [Status] - [Assignee]
>    [Brief description]
> 
> 2. **[Title]** - [Status] - [Assignee]
>    [Brief description]

---

## Example 4: Policy Question

**User:** "What's our refund policy for enterprise customers?"

**Reasoning:**
- Policy question → likely in docs/wiki
- Specific ("enterprise") → include in query
- Wants factual answer → use completion

**Search:**
```bash
python3 search.py "refund policy enterprise customers" --limit 5
```

**Response pattern:**
> According to your documentation, the enterprise refund policy is:
> [Policy details]
> 
> Source: [Document name]

---

## Example 5: Finding a Specific Item

**User:** "Find the Jira ticket about the payment bug"

**Reasoning:**
- Specific item search → keyword method may help
- "Payment bug" is descriptive → good query
- Wants the ticket → include link

**Search:**
```bash
python3 search.py "payment bug" --method hybrid --limit 10
```

**Response pattern:**
> Found the ticket: **JIRA-1234: Payment processing fails for international cards**
> 
> Status: In Progress
> Assignee: [Name]
> 
> Summary: [Description]
> Link: [URL]

---

## Example 6: No Results Handling

**User:** "What did we decide about the Berlin office?"

**Search:**
```bash
python3 search.py "Berlin office decision" --limit 10
```

**If no results:**
> I searched your connected apps but didn't find discussions about a Berlin office decision. A few possibilities:
> 
> - The discussion might be in a source that's not connected to Airweave
> - It might be under a different name (Germany office? European expansion?)
> - It might be too recent to be synced yet
> 
> Want me to try a different search, or can you give me more context?

---

## Example 7: Context for a Task

**User:** "Write a summary of Project Phoenix for the board meeting"

**Reasoning:**
- Needs context to complete task → search first
- Comprehensive info needed → higher limit
- Multiple aspects → broad query, then specific follow-ups

**Search:**
```bash
python3 search.py "Project Phoenix" --limit 25 --raw
```

Then potentially:
```bash
python3 search.py "Project Phoenix timeline milestones" --limit 10
python3 search.py "Project Phoenix budget costs" --limit 10
```

**Response pattern:**
> Based on your company data, here's a board-ready summary of Project Phoenix:
> 
> ## Overview
> [Summary from search results]
> 
> ## Key Milestones
> [From search results]
> 
> ## Current Status
> [From search results]
> 
> Sources: [List of documents/conversations referenced]
