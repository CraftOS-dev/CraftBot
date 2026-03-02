# Gmail Manager

Expert Gmail management skill for Clawdbot using Rube MCP integration.

## Features

- **Inbox Triage**: Efficient daily email processing workflow
- **Inbox Zero**: Systematic approach to empty inbox
- **Smart Search**: Gmail query syntax for finding emails
- **Batch Operations**: Bulk archive, label, and organize
- **Email Templates**: Cold outreach, follow-ups, quick replies

## Requirements

- Rube MCP connection with Gmail authenticated
- `RUBE_API_KEY` environment variable set

## Quick Start

```python
# Check inbox
GMAIL_FETCH_EMAILS
  arguments: {"q": "is:unread label:INBOX", "maxResults": 20}

# Send email
GMAIL_SEND_EMAIL
  arguments: {
    "to": "recipient@example.com",
    "subject": "Hello",
    "body": "Message here"
  }

# Archive processed
GMAIL_BATCH_MODIFY_MESSAGES
  arguments: {
    "ids": ["msg_id"],
    "removeLabelIds": ["INBOX"]
  }
```

## Available Tools

| Tool | Purpose |
|------|---------|
| `GMAIL_FETCH_EMAILS` | List/search emails |
| `GMAIL_GET_EMAIL_BY_ID` | Get email details |
| `GMAIL_SEND_EMAIL` | Send new email |
| `GMAIL_REPLY_TO_EMAIL` | Reply to thread |
| `GMAIL_CREATE_DRAFT` | Save draft |
| `GMAIL_BATCH_MODIFY_MESSAGES` | Bulk update labels |
| `GMAIL_LIST_LABELS` | Get all labels |
| `GMAIL_TRASH_MESSAGE` | Move to trash |

## Search Syntax

```
is:unread                    # Unread emails
from:name@example.com        # From sender
subject:keyword              # Subject contains
has:attachment               # Has attachments
newer_than:7d                # Last 7 days
```

## License

MIT
