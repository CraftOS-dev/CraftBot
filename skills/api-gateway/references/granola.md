# Granola Routing Reference

**App name:** `granola`
**Base URL proxied:** `mcp.granola.ai` (MCP Server)

## API Path Pattern

Granola uses the Model Context Protocol (MCP). All requests are POST requests to tool endpoints:

```
/granola/{tool_name}
```

## MCP Tools

### Query Meeting Notes
```bash
POST /granola/query_granola_meetings
Content-Type: application/json

{
  "query": "What action items came from my last meeting?"
}
```

**Parameters:**
- `query` (string, required): Natural language query about meetings

### List Meetings
```bash
POST /granola/list_meetings
Content-Type: application/json

{}
```

**Parameters:** None required. Returns recent meetings with metadata.

### Get Meetings
```bash
POST /granola/get_meetings
Content-Type: application/json

{
  "meeting_ids": ["0dba4400-50f1-4262-9ac7-89cd27b79371"]
}
```

**Parameters:**
- `meeting_ids` (array of strings, required): Meeting IDs to retrieve

### Get Meeting Transcript
```bash
POST /granola/get_meeting_transcript
Content-Type: application/json

{
  "meeting_id": "0dba4400-50f1-4262-9ac7-89cd27b79371"
}
```

**Parameters:**
- `meeting_id` (string, required): Meeting ID to get transcript for

**Note:** Only available on paid Granola tiers.

## Response Format

All responses follow MCP format:

```json
{
  "content": [
    {
      "type": "text",
      "text": "Response content here..."
    }
  ],
  "isError": false
}
```

## Notes

- All tool calls are POST requests with JSON body
- Meeting IDs are UUIDs (e.g., `0dba4400-50f1-4262-9ac7-89cd27b79371`)
- Users can only access their own meeting notes
- Free tier users limited to notes from last 30 days
- Transcripts require paid Granola tier
- Rate limit: ~100 requests/minute

## Resources

- [Granola MCP Documentation](https://docs.granola.ai/help-center/sharing/integrations/mcp)
- [Granola Help Center](https://docs.granola.ai)
