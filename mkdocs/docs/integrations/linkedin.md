# LinkedIn

The LinkedIn integration connects the agent to your LinkedIn account through the shared CraftBot app with one-click OAuth. The agent can read your profile, publish and manage posts, read post analytics, list connections, send and respond to connection requests, message connections, search jobs and companies, and read and follow organizations. LinkedIn has no event listener, so the agent acts when you ask it to.

## Requirements

| Requirement | Details |
|---|---|
| LinkedIn account | The agent acts as this account for every API call |
| Connection | One-click OAuth through the shared CraftBot app. You do not register a developer app of your own |
| Scopes | `openid`, `profile`, `email`, and `w_member_social`, granted at consent |
| Elevated access (optional) | People search, job search, and messaging often need LinkedIn partner-tier API access |
| Network access | CraftBot calls `api.linkedin.com` over HTTPS |

## Setup

1. Open **Settings → Integrations → LinkedIn** and click **Sign in with LinkedIn**. A browser tab opens at `linkedin.com/oauth`.
2. Sign in and approve the requested permissions (read your profile, post on your behalf). You are redirected back to CraftBot when consent completes. From chat, `/linkedin login` starts the same flow.
3. Verify with `/linkedin status`. It shows the connected LinkedIn ID.

`/linkedin logout` removes the credential.

## How it connects

**Authentication.** The OAuth flow runs through the shared CraftBot app and returns an access token that every call sends as a bearer token to `api.linkedin.com`. The integration reads your own LinkedIn ID from the OAuth userinfo response and builds `urn:li:person:<id>` for any self-reference, so you never supply it. The token and ID are stored in the credential store as `linkedin.json`. See [Credentials](credentials.md).

**Token refresh.** Access tokens last about 60 days and refresh automatically. A 401 usually means the app was disconnected on LinkedIn's side rather than an expiry, so reconnect with `/linkedin login`.

**URNs.** Recipients and objects are LinkedIn URNs, not usernames or numeric IDs: `urn:li:person:...` for people, `urn:li:organization:...` for companies, and `urn:li:share:...` for posts. They are not interchangeable, and the agent passes the raw URN through.

**Elevated access.** People search, job search, and messaging often return a note that LinkedIn restricts these endpoints to partner-tier apps. The agent surfaces that note to you. Retrying does not help; a different API tier does.

**No event listener.** No push events reach the agent, so it acts when you ask. Posts have a 3000-character limit, and the agent trims or splits longer text before publishing.

## What the agent can do

The 30 LinkedIn actions belong to the `linkedin` action set, which the agent loads as a task needs it. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Profile

| Action | Purpose |
|---|---|
| `get_linkedin_profile` | Get the authenticated user's profile |
| `get_linkedin_person` | Get a person's profile by person ID |

### Posts

| Action | Purpose |
|---|---|
| `create_linkedin_post` | Create a text post |
| `delete_linkedin_post` | Delete a post |
| `get_linkedin_post` | Get a single post by URN |
| `get_my_linkedin_posts` | Get your own posts |
| `get_linkedin_organization_posts` | Get an organization's posts |
| `reshare_linkedin_post` | Reshare an existing post with optional commentary |
| `like_linkedin_post` | Like a post |
| `unlike_linkedin_post` | Unlike a post |
| `get_linkedin_post_likes` | Get the reactions on a post |
| `comment_on_linkedin_post` | Comment on a post |
| `get_linkedin_post_comments` | Get the comments on a post |
| `delete_linkedin_comment` | Delete a comment on a post |

### Post analytics

| Action | Purpose |
|---|---|
| `get_linkedin_post_analytics` | Get analytics for a post |

### Connections

| Action | Purpose |
|---|---|
| `get_linkedin_connections` | Get the authenticated user's connections |

### Connection requests and invitations

| Action | Purpose |
|---|---|
| `send_linkedin_connection_request` | Send a connection request to a profile |
| `get_linkedin_sent_invitations` | Get invitations you have sent |
| `get_linkedin_received_invitations` | Get invitations you have received |
| `respond_to_linkedin_invitation` | Accept or ignore an invitation |

### Messaging and conversations

| Action | Purpose |
|---|---|
| `send_linkedin_message` | Send a message to LinkedIn users |
| `get_linkedin_conversations` | Get your conversations |

### Job search

| Action | Purpose |
|---|---|
| `search_linkedin_jobs` | Search for job postings |
| `get_linkedin_job_details` | Get details for a specific job |

### Company search and lookup

| Action | Purpose |
|---|---|
| `search_linkedin_companies` | Search companies by keywords |
| `lookup_linkedin_company` | Look up a company by its vanity name |

### Organizations

| Action | Purpose |
|---|---|
| `get_linkedin_organizations` | Get the organizations you administer |
| `get_linkedin_organization_info` | Get organization info by ID |
| `get_linkedin_organization_analytics` | Get organization analytics |
| `follow_linkedin_organization` | Follow an organization |
| `unfollow_linkedin_organization` | Unfollow an organization |

## Example requests

```
Post an update announcing that we just shipped v2, and keep it under 200 words.
```

```
Show my three most recent posts with their like and comment counts.
```

```
Search for remote data engineering jobs posted in the last week and summarize the top five.
```

```
Look up the company "acme-corp" and tell me their follower count and industry.
```

```
List my pending received invitations and accept the ones from people at Acme.
```

## Configuration

The LinkedIn integration has no configurable settings. Connecting stores only the OAuth credential, and the agent reads your LinkedIn ID from it. To change accounts, run `/linkedin logout` and connect again.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 401 on every call | The app was disconnected on LinkedIn, or the token was revoked | Reconnect with `/linkedin login` |
| Search or messaging returns a "note" about restricted access | The endpoint needs LinkedIn partner-tier API access | Apply for the higher API tier through LinkedIn. Retrying the same call does not help |
| Post rejected as too long | LinkedIn limits posts to 3000 characters | Ask the agent to trim or split the text before posting |
| A URN is rejected | A person, organization, or post URN was used in the wrong field | Confirm you are passing the URN the action expects (`person`, `organization`, or `share`) |
| Organization actions fail | Your account does not administer that organization | Use `get_linkedin_organizations` to confirm which organizations you can act on |

## Next

- [Twitter](twitter.md): posting and social actions with a mention-polling listener
- [Credentials](credentials.md): where the token is stored and how `/cred status` reports it
- [Actions and action sets](../core/concepts/actions-and-action-sets.md): how the agent loads LinkedIn actions on demand
