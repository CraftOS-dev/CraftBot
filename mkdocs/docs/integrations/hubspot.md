# HubSpot

The HubSpot integration connects the agent to your HubSpot portal. The agent can work with CRM objects (contacts, companies, deals, tickets), engagements (tasks, notes, calls, emails, meetings), lists, pipelines, properties, owners, associations, forms, marketing email, files, and conversations. You connect either through the shared CraftBot app with OAuth or with a Private App token. HubSpot has no active event listener, so the agent acts when you ask it to.

## Requirements

| Requirement | Details |
|---|---|
| HubSpot account (portal) | The agent acts on this portal for every API call |
| Connection method | OAuth through the shared CraftBot app, or a Private App access token |
| Private App token (token path) | Create at **app.hubspot.com → Settings → Integrations → Private Apps**. The token starts with `pat-` |
| CRM scopes | The grant or token needs read and write on the objects the agent will touch |
| Network access | CraftBot calls `api.hubapi.com` over HTTPS |

## Setup

Pick one of the two connection methods.

**OAuth (recommended):**

1. Open **Settings → Integrations → HubSpot** and click **Connect via CraftOS**. HubSpot opens in your browser to authorize the CraftBot app.
2. Approve the requested scopes. You are redirected back to CraftBot when consent completes. From chat, `/hubspot invite` starts the same flow.

**Private App token:**

1. Open **app.hubspot.com → Settings → Integrations → Private Apps** and click **Create a private app**. Name it, for example `CraftBot`.
2. On the **Scopes** tab, check the CRM read and write scopes the agent needs, at minimum.
3. On the **Auth** tab, copy the access token. Private App tokens start with `pat-`.
4. In CraftBot, paste the token into **Settings → Integrations → HubSpot** under **Private App Access Token**, or run `/hubspot login <private_app_token>`.

Verify either method with `/hubspot status`. It shows the connected portal and whether you connected via OAuth or a Private App token. `/hubspot logout` removes the credential.

## How it connects

**Authentication.** Both methods send `Authorization: Bearer <access_token>` to `api.hubapi.com`; the client does not branch on the method. The credential records which method you used so `/hubspot status` can report it, and it is stored as `hubspot.json`. See [Credentials](credentials.md).

**Token refresh.** OAuth access tokens expire after about 30 minutes and refresh automatically from the stored refresh token before each call. Private App tokens do not expire and skip refresh entirely. A 401 after an OAuth connection usually means the refresh token was revoked, so re-run `/hubspot invite` to reconnect.

**Object model.** Object IDs are numeric strings, so the agent passes them through as strings. Object types are plural (`contacts`, `companies`, `deals`, `tickets`), and property names are flat snake_case such as `firstname` and `dealstage`. Search uses HubSpot's `filterGroups` structure rather than a free-text query string. To move a deal or ticket, the agent updates its stage property.

**No active event listener.** No push events reach the agent by default, so it acts when you ask. The webhook subscription actions target a registered HubSpot App by its App ID, which is distinct from your portal ID and does not apply to Private App tokens. Skip those actions when you connect with a token.

## What the agent can do

The 90 HubSpot actions are grouped into action sets (`hubspot_contacts`, `hubspot_deals`, `hubspot_engagements`, and so on) that the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Contacts

| Action | Purpose |
|---|---|
| `list_hubspot_contacts` | List contacts with cursor pagination |
| `get_hubspot_contact` | Get a contact by ID, with optional properties and associations |
| `create_hubspot_contact` | Create a contact from a flat properties dict |
| `update_hubspot_contact` | Update a contact's properties |
| `delete_hubspot_contact` | Archive (soft-delete) a contact |
| `search_hubspot_contacts` | Search contacts by free-text query or property filter groups |
| `batch_get_hubspot_contacts` | Read up to 100 contacts in one call |
| `batch_create_hubspot_contacts` | Create up to 100 contacts in one call |
| `merge_hubspot_contacts` | Merge two contacts, keeping the primary and archiving the secondary |

### Companies

| Action | Purpose |
|---|---|
| `list_hubspot_companies` | List companies with pagination |
| `get_hubspot_company` | Get a company by ID |
| `create_hubspot_company` | Create a company |
| `update_hubspot_company` | Update a company's properties |
| `delete_hubspot_company` | Archive (soft-delete) a company |
| `search_hubspot_companies` | Search companies by query or filter groups |
| `batch_get_hubspot_companies` | Read up to 100 companies in one call |
| `batch_create_hubspot_companies` | Create up to 100 companies in one call |

### Deals

| Action | Purpose |
|---|---|
| `list_hubspot_deals` | List deals with pagination |
| `get_hubspot_deal` | Get a deal by ID |
| `create_hubspot_deal` | Create a deal |
| `update_hubspot_deal` | Update a deal's properties |
| `delete_hubspot_deal` | Archive (soft-delete) a deal |
| `search_hubspot_deals` | Search deals by query or filter groups |
| `batch_create_hubspot_deals` | Create up to 100 deals in one call |
| `move_hubspot_deal_stage` | Move a deal to a different pipeline stage |
| `list_hubspot_deals_by_pipeline` | List deals within a specific pipeline |

### Tickets

| Action | Purpose |
|---|---|
| `list_hubspot_tickets` | List support tickets with pagination |
| `get_hubspot_ticket` | Get a ticket by ID |
| `create_hubspot_ticket` | Create a support ticket |
| `update_hubspot_ticket` | Update a ticket's properties |
| `delete_hubspot_ticket` | Archive (soft-delete) a ticket |
| `search_hubspot_tickets` | Search tickets by query or filter groups |
| `close_hubspot_ticket` | Move a ticket to its closed stage |
| `list_hubspot_tickets_by_pipeline` | List tickets within a specific pipeline |

### Tasks

| Action | Purpose |
|---|---|
| `list_hubspot_tasks` | List task engagements |
| `create_hubspot_task` | Create a task, optionally associated with a CRM object |
| `update_hubspot_task` | Update a task's status, priority, or subject |
| `delete_hubspot_task` | Archive a task |

### Notes

| Action | Purpose |
|---|---|
| `list_hubspot_notes` | List note engagements |
| `create_hubspot_note` | Create a note, typically attached to a CRM object |
| `delete_hubspot_note` | Archive a note |

### Calls

| Action | Purpose |
|---|---|
| `list_hubspot_calls` | List logged call engagements |
| `log_hubspot_call` | Log a phone call as an engagement |

### Emails

| Action | Purpose |
|---|---|
| `list_hubspot_emails` | List logged email engagements |
| `log_hubspot_email` | Log an email as an engagement for record-keeping (does not send) |

### Meetings

| Action | Purpose |
|---|---|
| `list_hubspot_meetings` | List meeting engagements |
| `create_hubspot_meeting` | Create a meeting engagement record |
| `delete_hubspot_meeting` | Archive a meeting engagement |

### Lists

| Action | Purpose |
|---|---|
| `list_hubspot_lists` | List or search lists, optionally filtered to specific IDs |
| `get_hubspot_list` | Get a list by ID |
| `create_hubspot_list` | Create a manual (static) or dynamic (filter-based) list |
| `delete_hubspot_list` | Delete a list |
| `add_contacts_to_hubspot_list` | Add contact IDs to a static list |
| `remove_contacts_from_hubspot_list` | Remove contact IDs from a static list |

### Pipelines and stages

| Action | Purpose |
|---|---|
| `list_hubspot_pipelines` | List pipelines for an object type (deals or tickets) |
| `get_hubspot_pipeline` | Get a pipeline definition, including its stages |
| `create_hubspot_pipeline` | Create a new pipeline with stage definitions |
| `list_hubspot_pipeline_stages` | List the stages of a pipeline and their IDs |
| `update_hubspot_pipeline_stage` | Update a pipeline stage's properties |

### Owners

| Action | Purpose |
|---|---|
| `list_hubspot_owners` | List HubSpot users (owners) to find owner IDs |
| `get_hubspot_owner` | Get an owner by ID |

### Properties and property groups

| Action | Purpose |
|---|---|
| `list_hubspot_properties` | List all defined properties for an object type |
| `get_hubspot_property` | Get a property definition, including type and options |
| `create_hubspot_property` | Create a custom property |
| `update_hubspot_property` | Update a property's definition |
| `delete_hubspot_property` | Delete a custom property (built-ins cannot be deleted) |
| `list_hubspot_property_groups` | List property groups for an object type |

### Associations

| Action | Purpose |
|---|---|
| `create_hubspot_association` | Link two objects with a default or specific association type |
| `list_hubspot_associations` | List objects of a type associated with a source object |
| `delete_hubspot_association` | Remove an association between two objects |
| `list_hubspot_association_types` | List available association types between two object types |

### Forms and submissions

| Action | Purpose |
|---|---|
| `list_hubspot_forms` | List HubSpot forms |
| `get_hubspot_form` | Get a form definition by ID |
| `submit_hubspot_form` | Programmatically submit a form with field values |
| `list_hubspot_form_submissions` | List submissions for a form |

### Marketing emails and single-send

| Action | Purpose |
|---|---|
| `list_hubspot_marketing_emails` | List marketing email campaigns |
| `get_hubspot_marketing_email` | Get a marketing email campaign by ID |
| `send_hubspot_single_send` | Send a one-off transactional email from a template (irreversible) |
| `get_hubspot_marketing_email_statistics` | Get send, open, and click statistics for a marketing email |

### Files and folders

| Action | Purpose |
|---|---|
| `upload_hubspot_file` | Upload a local file to the file manager |
| `get_hubspot_file` | Get a file's metadata, including its URL |
| `delete_hubspot_file` | Delete a file from the file manager |
| `list_hubspot_folders` | List folders in the file manager |

### Conversations

| Action | Purpose |
|---|---|
| `list_hubspot_conversations` | List conversation threads in the inbox |
| `get_hubspot_conversation` | Get a conversation thread by ID |
| `list_hubspot_conversation_messages` | List messages in a conversation thread |
| `send_hubspot_conversation_message` | Send a message into a conversation thread (irreversible) |

### Webhook subscriptions

| Action | Purpose |
|---|---|
| `list_hubspot_webhook_subscriptions` | List webhook subscriptions for a HubSpot App |
| `create_hubspot_webhook_subscription` | Subscribe a HubSpot App to an event type |
| `delete_hubspot_webhook_subscription` | Delete a webhook subscription |

## Example requests

```
Find the contact with email dana@acme.com and show their open deals.
```

```
Create a deal called "Acme renewal" for $12,000 in the sales pipeline and associate it with Acme Corp.
```

```
Search for contacts created in the last 7 days who have no owner, and assign them to me.
```

```
Log a call on the Acme renewal deal with a note that they want a demo next week.
```

```
Move deal 78901 to the "Contract sent" stage and create a follow-up task for Friday.
```

```
List the marketing emails from last month and give me the open and click rates for each.
```

## Configuration

These settings live in **Settings → Integrations → HubSpot** and are stored in `hubspot_config.json` next to the credential. They fill in defaults when an action omits the matching field.

| Setting | Type | Default | Effect |
|---|---|---|---|
| Default deal pipeline (`default_pipeline_id`) | pipeline ID | empty | Pipeline used when `create_hubspot_deal` omits `pipeline`. Empty falls back to HubSpot's default pipeline |
| Default owner (`default_owner_id`) | owner ID | empty | Owner auto-assigned to new contacts, deals, and tasks when the action omits the owner. Use `list_hubspot_owners` to find IDs |
| Watched object types (`watch_object_types`) | list, e.g. `contact,deal,ticket` | empty | Object types the change listener polls. Empty disables polling |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 401 after an OAuth connection | The refresh token was revoked, or the shared app credentials are missing | Re-run `/hubspot invite` to reconnect |
| 401 with a Private App token | The token was deleted or its scopes changed | Create or reissue the Private App token and run `/hubspot login <token>` |
| 403 on a specific object | The grant or token lacks the CRM scope for that object | Add the read or write scope in the HubSpot app or Private App settings, then reconnect |
| `submit_hubspot_form` fails | Wrong form ID or portal ID | Confirm the form ID with `list_hubspot_forms`. Form submission posts to a separate host and uses the IDs, not the token |
| Webhook actions return an App ID error | You are connected with a Private App token, or passed a portal ID | Use these actions only with a registered HubSpot App, and pass its App ID from the developer console |
| Rate limit or 429 errors | Standard tier allows about 100 requests per 10 seconds per portal | Respect the `Retry-After` header and batch the work |

## Next

- [Stripe](stripe.md): payments and billing on the same key-based, no-listener pattern
- [Credentials](credentials.md): where the token is stored and how `/cred status` reports it
- [Actions and action sets](../core/concepts/actions-and-action-sets.md): how the agent loads HubSpot actions on demand
