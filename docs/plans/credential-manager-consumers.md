# Credential Manager: implementation and acceptance record

16 October 2026. The shared Windows vault, protected host and consumer paths are
implemented in this checkout. Windows installation, private-desktop interaction
and installed acceptance remain deferred. No service has been installed and no
live source, access-token or session store has been read or migrated during this
work. The ticket's release gate remains open until native acceptance passes.

## Components and dependencies

| Plan | Implemented components | Acceptance dependency |
| --- | --- | --- |
| CM-01–03 | Independent owner/profile identity; encrypted/versioned storage; grants/audit; SYSTEM host; AppContainer workers; native consent and private entry/view | Reviewed installation and actual OS containment/owner tests |
| CM-04 | Shared Credentials settings, profiles, typed entry, search, private view, versioned edit/delete, lock, activity/revoke | Human interaction, themes, keyboard and error-state checks |
| CM-05 | Browser reference selection and fixed HTTPS form helper; destination/navigation checks; generated-cookie transfer; owner handoff | Reviewed site helper and real sign-in/handoff checks |
| CM-06 | Integration source SPI, placeholder clients with constrained transports, public account selection, polling grants and trusted Discord Gateway receiver | Approved provider operations and real provider/listener checks |
| CM-07 | Model SDK transport, streaming/cancellation, REST/media, AWS signing, reference-pool rotation, confidential OAuth exchanges | Provider/model/media checks and unchanged generated-token refresh |
| CM-08 | Separate agent/Agent App credential workers; scoped launch/result/staging/stop; discovery, secure entry and saved-credential actions | Native identity, cross-app denial and interrupted-job checks |
| CM-09 | Verified resumable browser/model/integration/env migration; ambiguous-source reporting; export exclusions; synthetic leak/continuity tests | Offline owner cutover after relevant consumer acceptance |

UI metadata belongs only to its mounted view, with correlated replies and bounded
pages. Retired Mini Browser vault CRUD and raw autofill are disabled. Ordinary
provider clients receive placeholders; SDKs receive no raw-key resolver or
vault-authenticated client. A ContextVar selects transport only: it is not
authority. The service independently checks the actual worker, profile, version,
operation, destination and owner-approved grant.

Labels, service/account identifiers, origins and reference UUIDs are visible
metadata. Do not enter source values into labels. Source entry/private view use
the SYSTEM-only native desktop. Global clipboard copy/cut is disabled because
same-user processes can observe the ordinary clipboard. Python/.NET strings do
not promise physical memory zeroization; protection is the SYSTEM process/ACL
boundary and bounded lifetime. Desktop capture/hook denial and guardian crash
recovery still require installed acceptance.

## Installed policy and output

The default catalog has **922 descriptors**: 118 model/media and 804
integration/authentication operations, including 767 checked-in REST routes. The developer
generator reads provider source only; the protected host loads static sealed
metadata, never provider code, AST, agent code or runtime endpoint settings.
The registry accepts at most 1,024 descriptors.

Each descriptor fixes HTTPS origin, method, endpoint/resource template, allowed
query roots, encoding, authentication and output format. Resource arguments are
bounded relative segments with canonical round trips; they cannot introduce a
host, URL, traversal or encoded separator. Only installed Stripe business headers
are forwarded. Auth headers, cookies, redirects and proxy settings are not caller
inputs. DNS uses at most four secret-free resolver threads and a ten-second wait;
all answers must be public. Connections use a checked numeric address and verify
the original TLS hostname. Redirects are never followed.

The --helpers-file option replaces the entire default catalog. Include every
desired descriptor. The build options --tenant-origin jira=https://tenant.atlassian.net
and --tenant-origin posthog=https://eu.posthog.com select reviewed fixed origins.
Mutable settings cannot install destinations. Each vault item must separately
permit its actual origins, including https://gateway.discord.gg for Discord
listening and https://api-data.line.me for LINE media.

| Surface | Implemented policy | Limits/handoff |
| --- | --- | --- |
| OpenAI-compatible / Anthropic | Chat, Responses/Messages, models, embeddings and fixed image routes | Providers may not implement every route; custom hosts need reviewed descriptors |
| OpenAI media/audio | Image JSON/multipart, transcription text and speech bytes | Bounded media, safe MIME types and relative filenames |
| Gemini | Model-resource generate/embed/predict/video submit, cache create/delete, operation polling and fixed authenticated downloads | Unknown download hosts/redirects fail closed; inline video is capped at 23 MB, then existing keyframe fallback applies |
| BytePlus | Chat/Responses/embedding and video task submit/poll | Generated unauthenticated media URLs keep their original download path |
| Bedrock | Host-only static-pair SigV4 Converse and reference facade | Default model/region fixed; no arbitrary signer. Temporary/session credentials keep their original path |
| Static integrations | GitHub, Figma, Slack, Discord bot, Stripe, Notion, HubSpot, PostHog, Supabase, LINE, Telegram Bot, WhatsApp Business and configured Jira REST resources | Unknown/generic URLs, unsupported MIME/redirect routes and SDK-specific source-auth protocols fail closed |
| Confidential OAuth | Google, Slack, LinkedIn, HubSpot, Figma, Notion, Supabase and LINE fixed exchanges | Only source client secrets are injected. Generated access/refresh tokens return to existing provider/persistence callbacks |
| Twitter OAuth1 | Host HMAC-SHA1 signing for 28 installed JSON REST routes, account verification and one fixed multipart media upload | App key/secret stay in a service-secret item. The existing generated user access-token pair stays in the account store and is staged per request. No generic signer or new three-legged OAuth flow |
| Lark family | Tenant-token mint/refresh and WebSocket endpoint discovery use the host; messaging/calendar/drive retain their original clients | App secret becomes an inline reference. Generated tenant token, expiry and WebSocket session URL stay with the existing provider/SDK. Global Larksuite endpoints only |
| Telegram MTProto | Fixed send-code, complete-code, QR and saved-password completion helpers | App hash and optional saved 2FA password stay in a service-secret item. Generated pending/authorized StringSessions remain with the existing auth/account owner. No arbitrary TL methods, SDK callback or proxy |
| Browser | Reviewed conventional HTTPS form and selected generated secure cookies | JavaScript-only forms, cross-origin challenges, MFA/CAPTCHA/passkeys and unsupported pages use owner handoff/system-browser OAuth |
| Subscription OAuth | Existing token owners, normal system-browser connection and refresh | No password-to-token shortcut; saved Gmail credentials do not replace OAuth consent |

Polling can request repeated permission for one installed GET operation and one
immutable worker. Native consent displays that parameters may vary within the
route and permission lasts at most the worker's 15-minute lease. Each dispatch
still needs a fresh one-use capability. Writes cannot obtain repeat permission.
Lock, expiry and revocation block subsequent use; a replacement worker needs
consent again. Discord source-bot Gateway identification, heartbeat and sanitized
events run in the protected host. Voice/other SDK authentication is not an
unrestricted extension of this helper. Generated-token/session clients retain
their existing implementations.

Network work uses asynchronous jobs so control RPC remains available. Identity,
vault and SQLite reservations cover authorization through authenticated request
dispatch, then release while reading the response. One-use authority is spent
before release. Native explicit lock resets the host and **all profiles**, keys
and workers. Idle profile lock cancels its active jobs. Revocation aborts matching
jobs and denies future dispatch; already sent provider effects cannot be
retracted. Source lock/removal does not sign out existing browser/OAuth sessions.

SSE is validated and relayed incrementally. Bounded semantic holdback retains
possible source prefixes across delta events, rejecting split echoes before
releasing the first fragment. Full literal/common encoded echoes are scrubbed.
This guards accidental echoes from approved services, not every encoding a
malicious service could invent. Closing model streams/cancelling async actions
stops their jobs. Native prompts are human interactions; pending cancellation is
applied when the prompt/control call returns.

Staged JSON is capped at 32 MB per worker and 64 MB aggregate; ordinary JSON
responses at 2 MB and selected media at 64 MB. Retained sanitized output is capped
at 96 million characters per job and 192 million across jobs. There are at most
16 workers. JSON/SSE jobs have a 600-second network budget, bounded connection/TLS
setup, cancellation socket abort and a 15-minute lease. Response chunks account
for worst-case Unicode escaping in the 64 KiB pipe frame. Catalog, item and grant
discovery are paged. Provider error bodies/arbitrary headers are dropped.

## Offline cutover and unsupported records

Owner-only commands accept paths/IDs, never source values:

    python scripts/credential_host.py migrate_settings PROFILE ABSOLUTE_SETTINGS_JSON
    python scripts/credential_host.py migrate_browser PROFILE ABSOLUTE_LEGACY_VAULT_ENC
    python scripts/credential_host.py migrate_integration PROFILE PROVIDER ABSOLUTE_PROVIDER_ACCOUNTS_JSON
    python scripts/credential_host.py migrate_integration PROFILE slack ABSOLUTE_SLACK_ACCOUNTS_JSON --source-account ACCOUNT_ID
    python scripts/credential_host.py migrate_environment PROFILE ABSOLUTE_DOT_ENV

Stop every application/source writer first. Source reads/publication impersonate
the limited enrolled owner; destination vault/key access runs as SYSTEM. Local
paths/reparse points, retained source handles and snapshot digests are checked.
Encrypted imports are read back before source retirement. Stable IDs support
retry after interrupted commit; changed source/target conflicts abort. Digest
checking is not atomic against an independent pathname-renaming writer, hence
the offline requirement. No migration runs at startup.

Model keys/pools and supported static AWS settings become references. Temporary
AWS fields with session tokens remain unchanged. Browser migration preserves IDs,
archives old ciphertext and separately encrypts its recovery key before verified
legacy-file removal. Browser profiles/cookie/session directories are untouched.

Integration migration preserves account IDs, primary, aliases, listener flags,
timestamps and generated-token/session fields. Known manual sources become
references. OAuth account client_secret fields can become references without
turning those accounts into source-key clients. Missing/ambiguous provenance is
reported for explicit selection; OAuth mode/refresh tokens cannot be overridden.
Jira/PostHog origins must match the reviewed package. WhatsApp new connections
also supply and verify their public Phone Number ID.

Environment migration recognizes ENV_MODEL_KEYS (including XAI/ZAI/SAKANA/DASHSCOPE
aliases) and explicit ENV_OAUTH_KEYS. Other settings, generated tokens/sessions,
BOM, line endings and trailing comments are preserved. Duplicate/dynamic eligible
assignments abort; no environment code executes. Unknown credential-shaped
assignments remain in place and are counted for review.

Twitter account migration groups only `api_key`/`api_secret` in a service-secret
item and adds `source_reference`; its access token and token secret are preserved.
Lark, Lark Calendar and Lark Drive replace only `app_secret` inline; Telegram User
replaces only `api_hash` inline. These records keep their generated tokens,
refresh fields, expiry, session strings, identity, aliases and listening settings.
Environment migration also recognizes `TELEGRAM_API_HASH` and preserves
`TELEGRAM_API_ID` and unrelated token/session assignments. No live migration has run.

For new Twitter connections, save fields `api_key,api_secret` under service-secret
with origins `https://api.twitter.com` and, for media, `https://upload.twitter.com`.
Supply the reference and existing generated user-token pair in the normal connect
form. For Lark, save the app secret as an API-key item for
`https://open.larksuite.com` and supply the reference plus public App ID.
For Telegram, save service-secret fields `api_hash` and, when needed, `password`
for `https://api.telegram.org`; supply the reference, API ID, phone and login code.
The source password never goes through the connect form. Hash-only entries must
be recreated with both fields before starting a new 2FA login; existing saved
passwords can be corrected by native edit. Updating a reference version invalidates
old grants. The installed helper names also expose QR/password completion to the
credential interface; the current account connect UI remains the phone-code flow.

MTProto uses pinned Telethon 1.45.0 and in-memory StringSessions. Every socket
selects a sealed production DC IPv4 address and port 443, including DC migrations;
staged/server-provided addresses, proxies and arbitrary destinations cannot
override it. Initial connection and operation deadlines, cancellation and private
SDK logging apply. New DC addresses require a reviewed package update. Established
consumer sessions use an inert app-hash placeholder, with no interactive fallback
on revocation; reconnect uses the protected login helpers. MTProto's catalog HTTPS
origin is a policy identifier; transport is Telegram's authenticated/encrypted
MTProto TCP protocol, not an invented HTTP endpoint.

Other unlisted/custom source protocols remain unsupported and retain their legacy
protection until a dedicated reviewed adapter is installed. Existing raw/embedded
application defaults are not automatically converted. This is explicit unsupported
record handling in CM-09, not migration of every authentication store.

Profile exports exclude protected/legacy vaults, .env files, provider account
documents and credential directories. Agent App export/import keeps its existing
credential/session exclusions.

## Automated evidence and remaining release gate

Final automated results and replacement package hashes are recorded below after
packaging. Tests use synthetic values and temporary stores. They do not prove
private-desktop security, actual AppContainer containment or every provider API.
The earlier CM-03, CM-04–09, credential-host-auth-v1 and credential-host-auth-v2 packages are obsolete.

Installed acceptance must cover SYSTEM key round trips and consumer denial of
key/file/process/network access; native consent success/decline/wrong owner;
private entry/view and capture/hooks; guardian recovery; cross-app/profile/replay
denial; lock/suspend/logoff/stop; streaming/cancel/listeners; and supported offline
cutover followed by unchanged existing token/session use. The native verifier
contains a synthetic containment probe and requires the reviewed enrollment
owner UUID. It has not been run installed.

Implementation references:
[Windows secure prompt](https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-creduipromptforwindowscredentialsw),
[desktop attachment](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setthreaddesktop),
[Windows hooks](https://learn.microsoft.com/windows/win32/winmsg/using-hooks),
[AWS SigV4](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-create-signed-request.html),
[Bedrock Converse](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html),
[WebSocket socket/TLS/proxy controls](https://websockets.readthedocs.io/en/15.0.1/reference/sync/client.html).

Authentication references:
[X OAuth1 signature construction](https://docs.x.com/fundamentals/authentication/oauth-1-0a/creating-a-signature),
[Lark SDK WebSocket discovery](https://github.com/larksuite/oapi-sdk-python/blob/v1.7.5/lark_oapi/ws/client.py),
[Telegram user authorization](https://core.telegram.org/api/auth),
[Telegram production DC defaults](https://github.com/telegramdesktop/tdesktop/blob/dev/Telegram/SourceFiles/mtproto/mtproto_dc_options.cpp).

## Pre-install security review fixes

All eight review findings are addressed in code. These are pre-install checks;
Windows installation and interactive/native/provider acceptance remain deferred.
No live source, access-token, refresh-token, cookie or session store was read,
migrated or changed during these fixes.

| Finding | Change | Regression evidence |
| --- | --- | --- |
| Public frame expansion could reset the host | Native envelope serialization/ASCII expansion runs before starting or touching the Python worker and outside its reset handler. Public frames stay at 64 KiB; authenticated envelopes have a separate 400,000-character bound, aligned with Python. | Compiles the actual C# host with a noninteractive reflection probe; exercises maximum plain/Unicode expansion and rejects oversized public frames. No service starts. |
| One-use consent did not bind the actual request | Broker pins a canonical SHA-256 before native approval and freezes/rechecks request data before dispatch. Public callers must stage the request first. Private native review shows the resolved resource, method, account/profile/version, actual snapshot hash and meaningful parameters. Authentication values are hidden; values over 8,192 characters show length/hash with an explicit content notice. Reviews too large to represent safely fail closed. | Changed path, query and recipient/body; approval without a body; mutation after approval; actual public discard/re-upload after consent; canonical ordering and replay. All altered requests fail before network dispatch. |
| Helper metadata hid completed worker results | `program_result` returns the worker's explicit `complete()` value independently of `result` (helper status) and `response` (sanitized chunks). Agent App bridge and owner CLI expose these channels with existing run ownership checks. | Two SDK helper calls followed by a computed result; helper body and program result independently readable; recycled controllers and other projects denied. |
| Lease expiry left privileged jobs running | Deadline timer closes the whole launch: cancels the helper, kills the consumer, releases controller handles and revokes the binding. A background watcher also handles controller death and consumers that exit with active helper work. Close is idempotent; job creation is guarded against concurrent expiry. | Invokes the actual timer callback without another RPC, verifies helper cancellation/revocation and single close; checks disconnected-controller teardown. |
| App/deployment claims appeared trusted | Native launch and use review label caller kind/name/deployment as unverified. Actual code SHA-256 and kernel-bound worker identity remain pinned. Launch metadata explicitly reports `identity_verified: false`; no trusted enrollment or name-based permission reuse is implied. | A direct caller claiming a trusted app/live deployment still sees unverified labels and the actual submitted snapshot hash. |
| Scratch DACL lacked a writable integrity level | Only per-worker scratch receives an inheritable Low mandatory label; runtime, snapshots and vault retain their existing protected labels/DACLs. | Converts actual Windows security descriptors and checks Low SID, inheritance, SYSTEM ownership and protected DACL; read-only snapshot has no Low label. Deferred native probe now tests scratch read/write/delete and denies snapshot writes. |
| Generic isolated actions lacked profile wiring | Settings > Credentials explicitly selects/disables an action profile using native owner consent. Preference is stored only in the protected service's `action-profile.json`, outside settings/profile bundles. App startup passes a resolver through ActionManager to ActionExecutor; UUID validation fails closed and action input cannot override it. Each launch retains its chosen profile. Owner CLI exposes the same preference. | Owner refusal does not persist; unknown profiles fail; select/read/disable round trips; actual executor resolves the selected UUID and rejects invalid selection despite action/input profile claims. |
| Integration CLI still requested raw secrets | Connect accepts a vault reference plus provider-specific named public identifiers. No positional secret mapping or raw-source usage hints remain. Shared invites follow the same rules; OAuth without arguments retains its callback flow. Twitter and Telegram interactive login use Settings so generated tokens/login codes are not requested in command history. | Valid Lark reference/App ID; raw, unknown, duplicate and positional fields rejected without echo; OAuth preserved; Twitter/Telegram directed to Settings. |

Repeated GET consent intentionally allows varying resource/query parameters within
the exact installed route for that isolated worker and lease. It is explicitly
identified as broader read authority in the native review, cannot authorize
writes, and still issues a fresh capability for each dispatch. One-use requests
bind all input, including existing generated authentication state, by hash; that
state is neither moved into the vault nor persisted in the consent transport.

Agent App consumers should poll `program_result` for arbitrary worker completion.
Transport wrappers that consume helper output continue to use `result` and
`response`. Result values remain untrusted consumer output, never owner proof.

Windows integrity references: [mandatory integrity control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)
and [label security information](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information).
The installed scratch test remains necessary to verify the label with a real
AppContainer token; descriptor tests alone do not establish native containment.

## Final review package and checks

The uninstalled replacement package is
C:\Users\Lenovo\.codex\tmp\credential-host-security-v1.
All **2,627** manifest hashes are verified, and all **44** packaged credential
source/policy files match the checkout. The **84,752,950-byte** payload imports
the protected host, request review and pinned dependencies, and instantiates all
**922** policies under isolated packaged Python without starting a service.
`credential-host-auth-v2` is superseded. The replacement remains uninstalled.

Manifest SHA-256:
6fc1b842ae920bd000c72782af89bc7c9cb2d578e709bc6a1e32dda27b4c7cea

Installer SHA-256:
8e3f613e58e1e7512fecaf0403ac92186b2d350fa44910f383c5d61a4b3f3dd9

Automated results: **564 tests and 130 subtests pass**, with **14** optional/platform
skips (423 credential/legacy-format tests and 141 integration regressions).
This includes 18 regression tests for the review fixes, an actual C# frame/envelope
probe and real Windows descriptor conversion, without elevation or installation.
All **124** changed/new Python files pass Ruff check/format and compilation.
Native package compilation, installer PowerShell syntax validation, frontend
TypeScript and production build pass. REST generation reproduces all **767**
checked-in routes. Existing Vite bundle-size and upstream Lark protobuf deprecation
advisories remain. Service queries confirm `CraftBotCredentialHost` is absent.

These checks do not establish installed native isolation, private-desktop capture
resistance or live-provider interoperability. The acceptance gate above remains
open by the owner's explicit instruction to leave the service uninstalled. No
live migration ran. Any protected-code change after packaging requires another
package/hash review before installation.
