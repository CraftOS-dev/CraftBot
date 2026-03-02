---
name: github
description: |
  GitHub API integration with managed OAuth. Access repositories, issues, pull requests, commits, branches, and users.
  Use this skill when users want to interact with GitHub repositories, manage issues and PRs, search code, or automate workflows.
  For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
compatibility: Requires network access and valid Maton API key
metadata:
  author: maton
  version: "1.0"
  clawdbot:
    emoji: 🧠
    requires:
      env:
        - MATON_API_KEY
---

# GitHub

Access the GitHub REST API with managed OAuth authentication. Manage repositories, issues, pull requests, commits, branches, users, and more.

## Quick Start

```bash
# Get authenticated user
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/github/user')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/github/{native-api-path}
```

Replace `{native-api-path}` with the actual GitHub API endpoint path. The gateway proxies requests to `api.github.com` and automatically injects your OAuth token.

## Authentication

All requests require the Maton API key in the Authorization header:

```
Authorization: Bearer $MATON_API_KEY
```

**Environment Variable:** Set your API key as `MATON_API_KEY`:

```bash
export MATON_API_KEY="YOUR_API_KEY"
```

### Getting Your API Key

1. Sign in or create an account at [maton.ai](https://maton.ai)
2. Go to [maton.ai/settings](https://maton.ai/settings)
3. Copy your API key

## Connection Management

Manage your GitHub OAuth connections at `https://ctrl.maton.ai`.

### List Connections

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=github&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'github'}).encode()
req = urllib.request.Request('https://ctrl.maton.ai/connections', data=data, method='POST')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Content-Type', 'application/json')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Get Connection

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections/{connection_id}')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

**Response:**
```json
{
  "connection": {
    "connection_id": "83e7c665-60f6-4a64-816c-5e287ea8982f",
    "status": "ACTIVE",
    "creation_time": "2026-02-06T03:00:43.860014Z",
    "last_updated_time": "2026-02-06T03:01:06.027323Z",
    "url": "https://connect.maton.ai/?session_token=...",
    "app": "github",
    "metadata": {}
  }
}
```

Open the returned `url` in a browser to complete OAuth authorization.

### Delete Connection

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections/{connection_id}', method='DELETE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Specifying Connection

If you have multiple GitHub connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/github/user')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Maton-Connection', '83e7c665-60f6-4a64-816c-5e287ea8982f')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### Users

#### Get Authenticated User

```bash
GET /github/user
```

#### Get User by Username

```bash
GET /github/users/{username}
```

#### List Users

```bash
GET /github/users?since={user_id}&per_page=30
```

### Repositories

#### List User Repositories

```bash
GET /github/user/repos?per_page=30&sort=updated
```

Query parameters: `type` (all, owner, public, private, member), `sort` (created, updated, pushed, full_name), `direction` (asc, desc), `per_page`, `page`

#### List Organization Repositories

```bash
GET /github/orgs/{org}/repos?per_page=30
```

#### Get Repository

```bash
GET /github/repos/{owner}/{repo}
```

#### Create Repository (User)

```bash
POST /github/user/repos
Content-Type: application/json

{
  "name": "my-new-repo",
  "description": "A new repository",
  "private": true,
  "auto_init": true
}
```

#### Create Repository (Organization)

```bash
POST /github/orgs/{org}/repos
Content-Type: application/json

{
  "name": "my-new-repo",
  "description": "A new repository",
  "private": true
}
```

#### Update Repository

```bash
PATCH /github/repos/{owner}/{repo}
Content-Type: application/json

{
  "description": "Updated description",
  "has_issues": true,
  "has_wiki": false
}
```

#### Delete Repository

```bash
DELETE /github/repos/{owner}/{repo}
```

### Repository Contents

#### List Contents

```bash
GET /github/repos/{owner}/{repo}/contents/{path}
```

#### Get File Contents

```bash
GET /github/repos/{owner}/{repo}/contents/{path}?ref={branch}
```

#### Create or Update File

```bash
PUT /github/repos/{owner}/{repo}/contents/{path}
Content-Type: application/json

{
  "message": "Create new file",
  "content": "SGVsbG8gV29ybGQh",
  "branch": "main"
}
```

Note: `content` must be Base64 encoded.

#### Delete File

```bash
DELETE /github/repos/{owner}/{repo}/contents/{path}
Content-Type: application/json

{
  "message": "Delete file",
  "sha": "{file_sha}",
  "branch": "main"
}
```

### Branches

#### List Branches

```bash
GET /github/repos/{owner}/{repo}/branches?per_page=30
```

#### Get Branch

```bash
GET /github/repos/{owner}/{repo}/branches/{branch}
```

#### Rename Branch

```bash
POST /github/repos/{owner}/{repo}/branches/{branch}/rename
Content-Type: application/json

{
  "new_name": "new-branch-name"
}
```

#### Merge Branches

```bash
POST /github/repos/{owner}/{repo}/merges
Content-Type: application/json

{
  "base": "main",
  "head": "feature-branch",
  "commit_message": "Merge feature branch"
}
```

### Commits

#### List Commits

```bash
GET /github/repos/{owner}/{repo}/commits?per_page=30
```

Query parameters: `sha` (branch name or commit SHA), `path` (file path), `author`, `committer`, `since`, `until`, `per_page`, `page`

#### Get Commit

```bash
GET /github/repos/{owner}/{repo}/commits/{ref}
```

#### Compare Two Commits

```bash
GET /github/repos/{owner}/{repo}/compare/{base}...{head}
```

### Issues

#### List Repository Issues

```bash
GET /github/repos/{owner}/{repo}/issues?state=open&per_page=30
```

Query parameters: `state` (open, closed, all), `labels`, `assignee`, `creator`, `mentioned`, `sort`, `direction`, `since`, `per_page`, `page`

#### Get Issue

```bash
GET /github/repos/{owner}/{repo}/issues/{issue_number}
```

#### Create Issue

```bash
POST /github/repos/{owner}/{repo}/issues
Content-Type: application/json

{
  "title": "Found a bug",
  "body": "Bug description here",
  "labels": ["bug"],
  "assignees": ["username"]
}
```

#### Update Issue

```bash
PATCH /github/repos/{owner}/{repo}/issues/{issue_number}
Content-Type: application/json

{
  "state": "closed",
  "state_reason": "completed"
}
```

#### Lock Issue

```bash
PUT /github/repos/{owner}/{repo}/issues/{issue_number}/lock
Content-Type: application/json

{
  "lock_reason": "resolved"
}
```

#### Unlock Issue

```bash
DELETE /github/repos/{owner}/{repo}/issues/{issue_number}/lock
```

### Issue Comments

#### List Issue Comments

```bash
GET /github/repos/{owner}/{repo}/issues/{issue_number}/comments?per_page=30
```

#### Create Issue Comment

```bash
POST /github/repos/{owner}/{repo}/issues/{issue_number}/comments
Content-Type: application/json

{
  "body": "This is a comment"
}
```

#### Update Issue Comment

```bash
PATCH /github/repos/{owner}/{repo}/issues/comments/{comment_id}
Content-Type: application/json

{
  "body": "Updated comment"
}
```

#### Delete Issue Comment

```bash
DELETE /github/repos/{owner}/{repo}/issues/comments/{comment_id}
```

### Labels

#### List Labels

```bash
GET /github/repos/{owner}/{repo}/labels?per_page=30
```

#### Create Label

```bash
POST /github/repos/{owner}/{repo}/labels
Content-Type: application/json

{
  "name": "priority:high",
  "color": "ff0000",
  "description": "High priority issues"
}
```

### Milestones

#### List Milestones

```bash
GET /github/repos/{owner}/{repo}/milestones?state=open&per_page=30
```

#### Create Milestone

```bash
POST /github/repos/{owner}/{repo}/milestones
Content-Type: application/json

{
  "title": "v1.0",
  "state": "open",
  "description": "First release",
  "due_on": "2026-03-01T00:00:00Z"
}
```

### Pull Requests

#### List Pull Requests

```bash
GET /github/repos/{owner}/{repo}/pulls?state=open&per_page=30
```

Query parameters: `state` (open, closed, all), `head`, `base`, `sort`, `direction`, `per_page`, `page`

#### Get Pull Request

```bash
GET /github/repos/{owner}/{repo}/pulls/{pull_number}
```

#### Create Pull Request

```bash
POST /github/repos/{owner}/{repo}/pulls
Content-Type: application/json

{
  "title": "New feature",
  "body": "Description of changes",
  "head": "feature-branch",
  "base": "main",
  "draft": false
}
```

#### Update Pull Request

```bash
PATCH /github/repos/{owner}/{repo}/pulls/{pull_number}
Content-Type: application/json

{
  "title": "Updated title",
  "state": "closed"
}
```

#### List Pull Request Commits

```bash
GET /github/repos/{owner}/{repo}/pulls/{pull_number}/commits?per_page=30
```

#### List Pull Request Files

```bash
GET /github/repos/{owner}/{repo}/pulls/{pull_number}/files?per_page=30
```

#### Check If Merged

```bash
GET /github/repos/{owner}/{repo}/pulls/{pull_number}/merge
```

#### Merge Pull Request

```bash
PUT /github/repos/{owner}/{repo}/pulls/{pull_number}/merge
Content-Type: application/json

{
  "commit_title": "Merge pull request",
  "merge_method": "squash"
}
```

Merge methods: `merge`, `squash`, `rebase`

### Pull Request Reviews

#### List Reviews

```bash
GET /github/repos/{owner}/{repo}/pulls/{pull_number}/reviews?per_page=30
```

#### Create Review

```bash
POST /github/repos/{owner}/{repo}/pulls/{pull_number}/reviews
Content-Type: application/json

{
  "body": "Looks good!",
  "event": "APPROVE"
}
```

Events: `APPROVE`, `REQUEST_CHANGES`, `COMMENT`

### Search

#### Search Repositories

```bash
GET /github/search/repositories?q={query}&per_page=30
```

Example queries:
- `tetris+language:python` - Repositories with "tetris" in Python
- `react+stars:>10000` - Repositories with "react" and 10k+ stars

#### Search Issues

```bash
GET /github/search/issues?q={query}&per_page=30
```

Example queries:
- `bug+is:open+is:issue` - Open issues containing "bug"
- `author:username+is:pr` - Pull requests by author

#### Search Code

```bash
GET /github/search/code?q={query}&per_page=30
```

Example queries:
- `addClass+repo:facebook/react` - Search for "addClass" in a specific repo
- `function+extension:js` - JavaScript functions

Note: Code search may timeout on broad queries.

#### Search Users

```bash
GET /github/search/users?q={query}&per_page=30
```

### Organizations

#### List User Organizations

```bash
GET /github/user/orgs?per_page=30
```

Note: Requires `read:org` scope.

#### Get Organization

```bash
GET /github/orgs/{org}
```

#### List Organization Members

```bash
GET /github/orgs/{org}/members?per_page=30
```

### Rate Limit

#### Get Rate Limit

```bash
GET /github/rate_limit
```

Response:
```json
{
  "rate": {
    "limit": 5000,
    "remaining": 4979,
    "reset": 1707200000
  },
  "resources": {
    "core": { "limit": 5000, "remaining": 4979 },
    "search": { "limit": 30, "remaining": 28 }
  }
}
```

## Pagination

GitHub uses page-based and link-based pagination:

```bash
GET /github/repos/{owner}/{repo}/issues?per_page=30&page=2
```

Response headers include pagination links:
- `Link: <url>; rel="next", <url>; rel="last"`

Common pagination parameters:
- `per_page`: Results per page (max 100, default 30)
- `page`: Page number (default 1)

Some endpoints use cursor-based pagination with `since` parameter (e.g., listing users).

## Code Examples

### JavaScript

```javascript
const response = await fetch(
  'https://gateway.maton.ai/github/repos/owner/repo/issues?state=open&per_page=10',
  {
    headers: {
      'Authorization': `Bearer ${process.env.MATON_API_KEY}`
    }
  }
);
const issues = await response.json();
```

### Python

```python
import os
import requests

response = requests.get(
    'https://gateway.maton.ai/github/repos/owner/repo/issues',
    headers={'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}'},
    params={'state': 'open', 'per_page': 10}
)
issues = response.json()
```

## Notes

- Repository names are case-insensitive but the API preserves case
- Issue numbers and PR numbers share the same sequence per repository
- Content must be Base64 encoded when creating/updating files
- Rate limits: 5000 requests/hour for authenticated users, 30 searches/minute
- Search queries may timeout on very broad patterns
- Some endpoints require specific OAuth scopes (e.g., `read:org` for organization operations). If you receive a scope error, contact Maton support at support@maton.ai with the specific operations/APIs you need and your use-case
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Missing GitHub connection |
| 401 | Invalid or missing Maton API key |
| 403 | Forbidden - insufficient permissions or scope |
| 404 | Resource not found |
| 408 | Request timeout (common for complex searches) |
| 422 | Validation failed |
| 429 | Rate limited |
| 4xx/5xx | Passthrough error from GitHub API |

### Troubleshooting: API Key Issues

1. Check that the `MATON_API_KEY` environment variable is set:

```bash
echo $MATON_API_KEY
```

2. Verify the API key is valid by listing connections:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Troubleshooting: Invalid App Name

1. Ensure your URL path starts with `github`. For example:

- Correct: `https://gateway.maton.ai/github/user`
- Incorrect: `https://gateway.maton.ai/api.github.com/user`

## Resources

- [GitHub REST API Documentation](https://docs.github.com/en/rest)
- [Repositories API](https://docs.github.com/en/rest/repos/repos)
- [Issues API](https://docs.github.com/en/rest/issues/issues)
- [Pull Requests API](https://docs.github.com/en/rest/pulls/pulls)
- [Search API](https://docs.github.com/en/rest/search/search)
- [Rate Limits](https://docs.github.com/en/rest/overview/resources-in-the-rest-api#rate-limiting)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
