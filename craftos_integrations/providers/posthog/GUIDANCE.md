# PostHog

Product analytics. Use it to answer questions about what users actually do,
and to control feature rollouts.

## Answering an analytics question

Almost every "how many / which / top N / trend" question is one HogQL query
through `run_posthog_query`. HogQL is ClickHouse SQL over PostHog's tables —
the main ones are `events`, `persons` and `sessions`.

```sql
-- top events last week
SELECT event, count() FROM events
WHERE timestamp > now() - interval 7 day
GROUP BY event ORDER BY count() DESC LIMIT 10

-- daily active users
SELECT toDate(timestamp) AS day, count(DISTINCT distinct_id) AS users
FROM events WHERE timestamp > now() - interval 30 day
GROUP BY day ORDER BY day

-- funnel-ish: users who did A then B
SELECT count(DISTINCT distinct_id) FROM events
WHERE event = 'signup_started' AND distinct_id IN (
  SELECT distinct_id FROM events WHERE event = 'signup_completed'
)
```

Do not guess event names. `list_posthog_event_definitions` returns what this
project actually tracks, and `list_posthog_property_definitions` returns the
filterable properties. Checking first is cheaper than a query that returns
zero rows for a spelling reason.

If a query covers more than a few weeks, use `run_posthog_query_async` and
poll `get_posthog_query_status` — the synchronous path will time out, and
retrying it just burns the project's query budget.

`draft_posthog_sql` asks PostHog itself to draft HogQL from a description.
Useful when the schema is unfamiliar; always read the SQL before running it.

## Saving work

A query answers a question once. An **insight** saves it as a chart, and a
**dashboard** groups insights. When a user asks for something they will want
again ("track this for me", "put this somewhere I can see it"), create the
insight and attach it to a dashboard rather than re-running the query each
time.

Create an **annotation** whenever a deploy, launch or incident is mentioned.
It costs nothing and it is what makes a spike explainable three weeks later.

## Feature flags

Flags are identified by **numeric id, not by key**. When the user says "turn
off the new-checkout flag", resolve the key to an id with
`list_posthog_feature_flags` first.

To turn a flag off, use `disable_posthog_feature_flag`. Do not use
`delete_posthog_feature_flag` — deleting is for flags nobody needs again, and
code still referencing a deleted flag gets the default value rather than the
off value.

To change a rollout percentage, use `set_posthog_feature_flag_rollout`, which
preserves the flag's other release conditions. `update_posthog_feature_flag`
with a fresh `filters` object replaces them wholesale and will silently drop
property targeting.

Before widening a rollout, `get_posthog_feature_flag_blast_radius` tells you
how many users a condition would match.

## Accounts and projects

One connected account is one PostHog **project**. If the user has several,
`list_posthog_projects` shows the ids and any operation takes a `project_id`
override. If an operation returns data from an unexpected project, that is the
account's default project — check with `get_posthog_current_user`.

## Failure modes worth recognising

- **403 on one resource but not others** — the personal API key was minted
  without that scope. Scopes cannot be added to an existing key; the user must
  create a new one. Say so rather than retrying.
- **401 everywhere** — usually the wrong host. US Cloud keys do not work
  against EU Cloud.
- **404 on a feature flag or insight** — an identifier shape mistake. Flags
  take the numeric id, not the key; insights take the numeric id, not the
  `short_id`.
- **Empty results from a correct-looking query** — check the event name
  against `list_posthog_event_definitions` before assuming there is no data.

## Deleting

Deletes here are soft and recoverable, except person deletion
(`delete_posthog_persons`), which is the GDPR erasure path and is permanent.
Confirm before calling that one.
