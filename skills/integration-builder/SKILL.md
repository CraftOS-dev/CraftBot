---
name: integration-builder
description: "Build a new craftos_integrations provider end to end — acquire the vendor's API surface, decide the auth strategy, triage scope, generate the provider/client/operations/docs/tests, and run the verification gates. Use when asked to add an integration for a third-party service (e.g. 'add a Linear integration', 'we need PostHog'), or to audit an existing one against the house conventions."
user-invocable: true
action-sets:
  - file_operations
  - core
---

# Integration builder

Produce a production-level `craftos_integrations` provider for one vendor.

The mechanical part of an integration — file layout, envelope, decorator shape,
tag conventions — is maybe 30% of the work and is already specified in
[craftos_integrations/README.md](../../craftos_integrations/README.md). The
other 70% is judgment: which endpoint groups an agent would realistically use,
whether the vendor's auth pools identity or quota, what the canonical
identifier shape is, which "delete" is really a PATCH.

**So: the machine owns the inventory, the checklist and the verification. You
own the scope and auth decisions.** Nothing here decides *what* to expose. It
decides whether you wrote down a defensible answer and whether the output
passes the gates.

Do not skip to stage 5. Stages 1–4 are what stop you generating 60 plausible
methods against endpoints that don't exist.

---

## Stage 1 — Acquire the API surface

Get a machine-readable endpoint list before writing anything.

In preference order:

1. **An OpenAPI/Swagger schema.** Most vendors publish one. Download it and
   parse it locally — do not read it through a doc-fetching tool.

   ```bash
   curl -sSL -o "$SCRATCH/<name>_schema.json" "https://<vendor>/api/schema/?format=json"
   ```

   Then group the paths by resource with a short Python script: for each path,
   the methods available. This is the inventory everything else hangs off.

2. **An in-repo API reference.** Check `skills/<name>-api/SKILL.md` and
   `skills/api-gateway/references/<name>.md` first — several vendors already
   have one, written against the live API, and they record quirks the spec
   does not (PostHog's soft-delete rule came from there).

3. **The official REST reference docs**, last. Cross-check the version and base
   URL.

**Hard-won:** vendor doc *pages* truncate when fetched and will silently give
you a partial endpoint list. The schema does not. If you find yourself fetching
a fourth doc page, stop and go get the schema.

Write the schema to the scratchpad, never the repo.

### What to extract

For each resource group: the list/get/create/update/delete paths, sub-resource
action endpoints (`/enable/`, `/archive/`, `/bulk_delete/`), the pagination
parameters, and the identifier type in each path.

Watch for surprises the spec makes obvious and memory does not:

- Action endpoints you'd otherwise hand-roll (`/feature_flags/{id}/enable/`).
- Resources with **no** DELETE (PostHog persons — erasure is `bulk_delete`).
- Listing that hangs off a parent you didn't expect (PostHog projects live
  under `/organizations/{id}/projects/`, not `/projects/`).

---

## Stage 2 — Decide the auth strategy

Run the three-question test from the README's "Choosing an auth strategy":

1. **Whose identity acts?** The user's, or one shared identity of ours?
2. **Whose rate limits apply?** Per user-account, or one pooled bucket?
3. **Whose app gets suspended if one user misbehaves?**

Any answer of "ours" → **the user supplies their own credentials**, whatever
the friction. All three "user's" *and* the vendor offers user-authorization
OAuth → OAuth with our embedded client credentials, one click.

Record the reasoning in the provider docstring. The next person will ask why,
and "we didn't check" is not an answer.

### Check whether OAuth actually exists

Do not assert from memory that a vendor has no OAuth. Check:

```
https://<vendor>/.well-known/oauth-authorization-server
```

It returns the real `authorization_endpoint`, `token_endpoint`,
`scopes_supported` and `code_challenge_methods_supported`. PostHog was assumed
token-only and turned out to support OAuth 2.0 with PKCE.

If OAuth exists but is blocked on infrastructure we don't have yet (a hosted
client-metadata document, a registered developer app), the right move is:
implement `oauth_spec()` with the real endpoints and scopes, keep `auth_type`
as `"token"`, and document the one-line flip. Ship the path that works; leave
the other one loaded.

**Never embed anything but OAuth client credentials.** No user tokens, no
server-side API keys.

### Then write

- `fields` — what the connect modal asks for. Include anything that varies per
  install: a region or host field is mandatory for any vendor with EU/US/self-
  hosted deployments, and its absence is invisible until an EU user hits a 401
  that looks like a bad key.
- `connect_help` — 3–5 steps, walked yourself in a fresh browser.
- `verify_token` — reject the wrong-credential-type by prefix *before* spending
  a request, with a message naming the right one. Every vendor with multiple
  key types has a confusable pair (Stripe `pk_`/`sk_`, PostHog `phc_`/`phx_`).
- `identity_of` — the stable account key. Ask "could one human have two of
  these?" A PostHog user routinely has several projects, so identity is
  `org:project`, not their email. Must be lowercase, stable, and must tolerate
  junk without raising.

---

## Stage 3 — Triage scope

List every endpoint group from stage 1. For each, decide keep or drop, with one
line of why.

Keep what an agent would plausibly be asked to do on the user's behalf. Drop:

- **Billing, subscriptions, usage** — money.
- **Org admin** — invites, roles, SSO, API-key management, 2FA. Privilege
  escalation surface. Drop even when the scopes would allow it.
- **Code/pipeline deployment** into the user's instance.
- **Products with their own large surface** that would double the count.

Then apply the coverage rule, which is where most integrations fail:

> **Mirror the API's verb set on every noun you keep.** For every list/get/
> create, expose update and delete unless the API genuinely lacks them. An
> integration that lists but cannot edit or delete is the #1 source of agent
> failure: the model picks it confidently, then cannot finish the job.

Target 30–75 operations. Under 30 almost always means you missed the
edit/delete/reply surface.

Write the dropped list into an exclusion block at the bottom of
`operations.py`, one line per group. It stops the next session re-litigating
the same decision.

---

## Stage 4 — Design the action sets

Group by the **noun** the operation acts on, never the verb. Prefix every tag
with the integration name (`posthog_insights`, not `insights`).

- One fine-grained set per resource category. None below 3 operations — merge
  it if it is.
- One umbrella set named exactly the integration id, carrying the high-value
  ~20%: primary-noun list/get/create/update, the main search or query entry
  point, and 1–2 operations per remaining category. **Target 15–25.**

The umbrella is what loads when the user says "use <vendor>". It is easy to
over-tag: PostHog's first pass came out at 30 and had to be trimmed.

**Trim on the right axis. If the umbrella can create a noun, it must be able to
delete that noun.** PostHog's trim demoted `delete_posthog_dashboard` while
keeping `create_posthog_dashboard`, purely to hit the 25 ceiling. The agent then
created a dashboard, could not find a way to remove it, fell back to
unauthenticated raw HTTP and got a 401. The size ceiling exists to protect the
context budget; the lifecycle rule exists to protect the agent from dead ends,
and it wins. `verify_integration.py` now fails the build on this.

When you are over the ceiling, demote in this order: convenience wrappers that
duplicate a more general operation (a `list_events` that is really a canned
query), discovery helpers the agent can reach another way, secondary-noun
updates, and cross-noun linking operations. Never a delete whose create you
kept.

Listener/config operations go in `<name>_listener`, never in a noun set.

---

## Stage 5 — Generate

One folder, `craftos_integrations/providers/<name>/`. **Full port shape** —
`provider.py`, `client.py`, `operations.py`, `INTEGRATION.md`, `GUIDANCE.md`,
`__init__.py`. Do **not** create `app/data/action/integrations/<name>/`; that
is the legacy bridge shape.

Register in `default_providers()` in `craftos_integrations/providers/__init__.py`,
in the "Full ports" block.

### client.py

One method per endpoint, `async`, returning the `Result` envelope from
`helpers.arequest`. Credential-injected: a `bind_credential(credential, persist)`
method, `has_credentials()`, `_load()`. No disk-credential path — that is
legacy plumbing that only exists in ported integrations.

- Base URL from the credential when the vendor has regions; a module constant
  otherwise.
- Clamp `limit` to 1–100, default 30; surface the vendor's cursor in the result.
- Strip unset keys before a PATCH so it never blanks a field the caller didn't
  mention.
- **Read-modify-write for partial updates of nested structures.** A blind PATCH
  of a `filters`-style object silently drops the parts the caller didn't send.
  PostHog's `set_feature_flag_rollout` reads the flag first for exactly this
  reason.
- If you compose the vendor's query language from agent-supplied values, escape
  string literals through one helper and use it everywhere.

### operations.py

One `client_op(...)` per client method. Schema-fragment builders (`_s`, `_i`,
`_b`, `_arr`, `_obj`) keep it declarative — return a **fresh dict** each call,
never a shared instance.

- `name`: verb-first, snake_case, carries the integration name.
- `description`: one sentence stating what it does, **which identifier it
  expects**, and what it returns. This is what the model reads to choose.
- `input_schema`: keys map 1:1 to the client method's kwargs. Always give
  `example` values. **Never declare an `account` key** — the host injects it.
- `parallelizable=False` on every mutation, or the runtime fans out duplicate
  creates.
- `destructive=True` on anything matching delete/clear/remove/revoke/destroy/
  cancel — the conformance suite enforces this by name.

### INTEGRATION.md

The gotchas, for whoever debugs this at 2am: identifier shapes per resource,
the soft-delete rule, auth failure modes with what they actually mean ("403 =
missing scope, retrying won't help"), rate limits with real numbers, and why
there is or isn't a listener.

### GUIDANCE.md

For the agent, not the maintainer: how to answer a typical question with this
integration, which operation to reach for first, the discovery calls that
prevent empty results, and the failure modes worth recognising. Write the
sentences you'd want in context when the model is deciding what to call.

### tests/integrations/test_<name>_conformance.py

Subclass `ProviderConformance` with credential fixtures — the real post-verify
shape, a degraded shape (missing optional identity), and `{}` for junk. Add
direct tests for `identity_of` composition, any host/URL normalization, and
each `verify_token` rejection branch with the HTTP call monkeypatched.

---

## Stage 6 — Verify

```bash
python scripts/verify_integration.py <name>
```

Gates: imports and registers · operation count, tag distribution, umbrella
size, umbrella create/delete lifecycle, mutation and destructive flags, no
`account` input · the conformance suite. Loop back until it passes.

Then run the whole suite — a new provider can break a hardcoded count
elsewhere:

```bash
python -m pytest tests/integrations -q
```

Use the CraftBot interpreter (`app/python_runtime.py` resolves it), not
whatever `python` points at.

---

## Stage 7 — Hand off

The offline gates cannot tell you whether the vendor accepts what you send.
**Do not call the integration done.** Give the user a smoke-test checklist —
one prompt per sub-set, in natural language, ending with a delete so soft-
delete behaviour gets confirmed:

```
"list my <primary noun>"
"create a <primary noun> called 'smoke test'"
"update it to ..."
"<the integration's main query/search verb>"
"delete the smoke test <primary noun>"
```

State plainly what is verified (structure, registration, conformance) and what
is not (that the API accepts these calls).

---

## Auditing an existing integration

`python scripts/verify_integration.py --all --no-tests` reports convention
drift across every shipped provider. Bridge ports report no operations and skip
the audit — expected, not a failure. Treat parallelizable mutations as real
bugs; treat umbrella-size and thin-set findings as cleanup.
