# References

Users can attach sessions and Agent Apps through **+ → Reference…** or type
`@` in the composer and filter suggestions as they type. Selecting a suggestion
adds a removable chip; unselected `@text` remains ordinary text. Enter/Tab selects
a suggestion, arrows navigate, and Escape dismisses. Email addresses do not open
the picker. Both entry points use one catalog and pending-reference selection. Discovery lists
main/ordinary chats and apps; internal Agent App sessions are hidden to avoid
duplicate entries.

## Data flow

The client sends `references: [{kind, targetId}]` with the ordinary message
envelope. It never supplies authoritative reference content. `ReferenceService`
validates the destination and source identities and composes the two providers.
The browser's existing attachment submission path accepts references as well,
without routing the request to a different session or running an app.

The server persists `ReferenceSnapshot` objects in the additive nullable
`chat_messages.reference_snapshots` JSON column, echoes the same snapshots to the
browser, and includes attributed source data in the destination's normal trigger
payload. History loading and reconnection preserve the chips and captured preview.
Persistence is required before a reference message is acknowledged. Accepted
reference retries with the same destination/clientId reuse their original snapshot
and do not enqueue another turn; concurrent duplicates share an in-flight gate.
This does not add an atomic transaction across chat storage and the separate
trigger queue: a process crash between their writes retains the pre-existing
delivery limitation. Do not advertise exactly-once delivery across crashes.

Captured excerpts stay with the destination history. Renaming or deleting a source
does not rewrite those copies; clearing/deleting the destination removes them.
An unavailable source disables navigation and further live reads. Sources are
scoped to the current local CraftBot account; this feature does not introduce a
separate tenant/ACL system.

## Providers and expansion

- `SessionReferenceProvider` reads only visible user/agent transcript text from
  the selected session. It excludes internal activity, stored reference excerpts,
  attachment bytes and executable UI artifacts. Pages use acceptance row order,
  a fixed high-water mark, and continuation offsets inside oversized messages.
  Read `nextCursor` until it is null to retrieve earlier material; each message
  chunk includes its messageId, speaker, timestamp and character offset. Clearing
  a source invalidates its cursors.
- `AgentAppReferenceProvider` captures allowlisted project metadata. For a running
  app it optionally reads bounded schema/operation declarations from the registered
  loopback describe endpoint. It does not follow redirects, launch apps, inspect
  their build transcripts, read records/files/secrets, or execute operations.
- `read_reference(kind, target_id, cursor?)` is a core read-only action. Its trusted
  `_session_id` must already contain a persisted attachment of that source. Every
  read checks membership and current source existence again. Results are explicitly
  live reads, separate from the original captured preview.

Initial limits are eight unique references, 8 KiB per excerpt and 32 KiB combined;
live pages are capped at 24 KiB. Sources share the total budget fairly. The existing
token counter additionally bounds rendered context to at most 8,192 tokens or
one eighth of the configured model context window, whichever is smaller. Smaller
captures are re-read at their actual bound so continuation cursors remain correct.
Normal context-engine compaction still handles the rest of the receiving history.
These are context data, never system instructions or permission grants.

To add a source, implement the provider's small async `capture(target_id, limit,
cursor)` contract, register it in `create_reference_service`, and extend the TS
ReferenceInput kind/catalog/navigation mapping and i18n labels. Providers return
label, excerpt, truncated, and nextCursor. They own source-specific access and
extraction; storage, message submission and prompt rendering remain generic.
Keep uploads, remote indexing, subscriptions, and source mutations separate.

## Failure handling and UI

Validation/storage failures return a clientId-correlated `message_rejected` event.
The pending bubble becomes an error with Retry and Edit controls. Edit restores
the original text, references, attachments and reply quote to the composer, allowing
an unavailable source to be removed. Retry payloads are held in memory until the
server echo; rejected unsent payloads are not durable across a page reload.
Messages containing references plus slash-prefixed text are ordinary messages.
Reference-only submissions receive a server-generated display label.

The frontend uses the existing textarea rather than a rich-text editor: the selected
`@query` is consumed and represented by the same chip as a + selection. Source
filtering is synchronous local metadata search, not transcript full-text search.
The + picker opens on hover as a compact nested menu with search, grouped sources,
selection toggles, and Escape/outside-click dismissal. Selecting a source closes
both menus and returns focus to the composer. Keyboard users can open it
with the right arrow, and touch users can still tap the entry. Chips use short single-line
labels and source-type icons. Captured previews retain their focus-managed dialog;
autocomplete owns active keyboard events before slash commands, input history, and send.

## Validation

From the repository root:

```powershell
python -m pytest tests/references tests/test_chat_storage_sessions.py tests/test_browser_ui_buffers.py tests/test_chat_read_receipts.py -q
python -m ruff check app/references app/data/action/reference_actions.py app/usage/chat_storage.py app/ui_layer/components/types.py app/ui_layer/adapters/browser_adapter.py app/agent_base.py tests/references
```

From `app/ui_layer/browser/frontend`:

```powershell
.\node_modules\.bin\tsc.cmd --noEmit
npm run build
.\node_modules\.bin\playwright.cmd test --workers=2
```

The Playwright fixture mounts the real composer/store/message components with an
offline transport. Python submission tests exercise the real browser adapter and
SQLite persistence with a fake agent, including mixed attachments, missing sources,
storage failure, and concurrent retries. No model, user database, running app, or
external connector is required. The repository's ESLint command currently has no
configuration file; it cannot run until that existing tooling gap is resolved.

Validation on 26 October 2026 after the edge-case fixes: 73 focused backend tests,
all 76 browser tests, and 90 repeated reference browser tests passed. Type checking,
production build, byte-compilation, and lint/format checks on the changed Python
files passed. Whole-repository lint still reports two pre-existing F402 errors in
`app/credentials/vault.py`; that file is unchanged from the `dev` base.

Additional isolated stress runs passed 100 concurrent eight-source captures,
250 concurrent reads, complete paging through a 1.68 MB Unicode message, and 1,000
contenders for one submission gate. Real-WebSocket tests with the actual browser
adapter and SQLite (stub agent) passed reload, retry replay, deletion, expansion,
and reconnect checks. A 500-request duplicate burst produced one accepted message;
50 unique requests were accepted once each, and 100 invalid requests were rejected.
The rapid-input reproduction now passes without waiting for an animation frame;
forged oversized cursor positions return validation errors instead of OverflowError.

The + submenu still renders all matching rows: a synthetic 6,001-source catalog
opened in approximately 0.7 seconds, while filtered search updates took 8–14 ms.
This remains a scalability consideration, not part of the two edge-case fixes.
No live model or production-state validation was performed.
