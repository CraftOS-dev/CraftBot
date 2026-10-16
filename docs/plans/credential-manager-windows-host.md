# CM-03 Windows protected host

Implementation is available; installed native acceptance is pending. This
environment is not elevated. Installing a SYSTEM service requires Windows
administrator approval, and secure-desktop authentication needs the human owner.
Do not mark CM-03 production-ready on compilation/unit tests alone.

## Boundary

`native/CredentialHost.cs` runs as the `CraftBotCredentialHost` SCM service under
SYSTEM. The installer places its executable, private Python 3.12 runtime, nine
hash-pinned runtime dependencies, bootstrap, helper catalog and worker code in
`%ProgramFiles%/CraftBotCredentialHost`. It assigns SYSTEM ownership and protected
DACLs before registering/starting the service. Imported user-site packages,
`.pth` files, checkout paths, current working directories and inherited user
environment variables are excluded. There is no developer-mode bypass.

The shared vault lives under `%ProgramData%/CraftBotCredentialHost/vaults`.
Its keys are in **the service account's** Windows credential facility. The human
owner SID and profile UUIDs remain separate from that OS storage identity.
Unrestricted ordinary user code therefore cannot read this service's vault/key
store merely by importing Python vault code. Administrator/SYSTEM compromise is
outside this boundary; credential consumers are never launched elevated.

The public local named pipe rejects remote clients, has a low mandatory label,
and grants data rights without `FILE_CREATE_PIPE_INSTANCE`. The server keeps the
first pipe instance open. The client verifies the kernel object's SYSTEM owner
before sending anything; it does not trust a server-provided PID/flag and does
not need SCM access from inside an AppContainer. Identification SQOS prevents
a squatter impersonating the client. SYSTEM is the trusted OS principal.

The service obtains each client's PID from the pipe kernel handle and retains
a live process handle/creation stamp. Identification-only pipe impersonation
also captures the actual pipe client's user/AppContainer SID. The private worker
envelope keeps these claims separate from client JSON and compares them to the
current process/token, rejecting exited or recycled processes. The worker opens the
real process/token, verifies the configured owner SID, actual AppContainer SID,
non-elevated token and membership in its private, retained job. Ordinary agent,
shell and Agent App bridge tokens cannot satisfy those checks. PID/SID strings
and `owner_authenticated`/`isolated` flags are never authority.

## Consumer launch

The owner transport accepts a bounded file-content snapshot, not a privileged
filesystem-copy path, executable name, command or environment. Paths reject
Windows aliases, traversal, streams, duplicate case names and reserved SDK/
runner files. A length-delimited SHA-256 revision pins names, content and entry.
Owner consent displays the revision, caller, deployment and selected profile.

`windows_host.IsolatedProcess` creates an AppContainer under the interactive
owner's limited token with no network/broad file capabilities. The process and
thread objects are SYSTEM-owned; same-user desktop code receives no injection
handle. A private kill-on-close job limits the consumer to one process and
512 MiB, applies UI restrictions and prohibits descendants; a 15-minute timer
terminates abandoned launches. Child creation is also restricted at creation.
The process starts suspended and enters the job before executing untrusted code.

Code and the standalone credential client are immutable to the consumer. Scratch
storage is separate. The environment contains only runtime/Windows paths and the
new scratch directory, with no bridge/provider secrets or token/session data.
Consumers communicate through references, one-use capabilities and coarse helper
outcomes. This first runtime supports bounded Python/standard-library workers;
it does not execute an existing arbitrary Node/web launch command with vault
authority. Such apps use a separate protected Python credential worker.

`ActionExecutor(credential_profile_id=...)` supports the explicit
`credential_isolated` mode; profile selection is host configuration, not action
bundle metadata. `AgentAppManager.launch_credential_worker(...)` creates a
separate live/development-bound launch with the actual snapshot revision.
Neither path falls back to an ordinary process if the service is unavailable.
The existing web/Node process and integration bridge receive no source secrets.

## Owner transport

The browser/WS/API bridge cannot approve, unlock, reveal or submit secret fields.
The configured unelevated Windows owner may request profile metadata, a launch,
initialize, lock, or secure entry. Initialize, launch and grant approval invoke
the installed native executable as SYSTEM in that owner's interactive session.
Its Windows credential prompt uses `CREDUIWIN_SECURE_PROMPT`, validates the
supplied account with Windows logon and compares the resulting SID to the
configured owner. Cancel, wrong account, unsupported providers and timeouts deny
the operation. Windows login credentials never enter Python or the public pipe;
native buffers are cleared and tokens closed. Password authentication is the
initial supported owner-verification mode; PIN/Hello-only configurations may be
unavailable and never fall back to a browser checkbox.

Source entry and owner-only private view use a SYSTEM-only desktop after
verification, with a bounded guardian to restore that exact desktop on exit.
Clipboard copy/cut is disabled. Credential request review uses this private
desktop too, after Windows owner authentication; an explicit review checkbox and
Approve button are required. Request data travels on the SYSTEM-only UI pipe,
never a command line. Installed acceptance of this boundary is pending.
It writes only to a random, SYSTEM-only pipe created by the worker, which checks
the actual native child PID. No secret fields pass through the owner CLI,
ordinary request payload, Redux, action logging or agent messages. The only
public result is a credential reference. `request_use` requires staged input and
displays the exact profile/account/version, actual snapshot hash, unverified
caller/deployment labels, operation, resolved endpoint and parameters. The broker
binds one-use approval to a canonical request hash, then issues a capability for
at most 30 seconds. Parameter changes require new approval. Large content uses
explicit length/hash notices, and oversized reviews fail closed. A repeat GET grant
requires separate explicit native consent, pins the exact operation/worker and
expires with its at-most-15-minute lease. Writes cannot request this mode.
Multiple matching accounts
require an explicit reference; no recent-account fallback exists.

The SCM host owns a kill-on-close supervisor job and kills its worker on crash,
session lock/logoff, suspend, stop or a
300-second request watchdog timeout (including a stuck resolver). Kernel
kill-on-close jobs terminate the consumers and native prompts. In-memory keys,
grants, bindings and capabilities disappear; vault ciphertext stays intact.
This never signs out or moves existing application tokens/sessions.

## Build, install and operate

Use Windows x64 CPython 3.12 for the protected runtime build. Normal CraftBot can
retain its own interpreter. Eight dependencies use the dedicated checked-in
`requirements/credential-host-win_amd64-py312.txt` with publisher wheel hashes.
Telethon's pyaes dependency has no publisher wheel: the builder verifies its
pinned publisher source-archive SHA-256 and copies only four fixed Python files
plus its license. It never runs setup.py, a build backend or archive extractall.
The native host compiles using Windows' .NET Framework compiler.

```powershell
python scripts/build_credential_host.py <new-package-directory> --owner-sid <Windows-owner-SID>
```

The builder creates `payload/`, `manifest.json`, `Install.ps1` and prints the
manifest SHA-256. Review them before elevation. The installer requires that
exact digest, verifies the protected copies, creates fresh Program Files/data
roots and an automatic SYSTEM service. Existing service/state is never reset or
overwritten. It does not read or migrate any current credential/token/session
store. A trusted administrator must install/review code updates; consumer RPC
cannot modify the helper catalog or executable files.

```powershell
# Elevated PowerShell: execute the reviewed, hash-verified installer script
# from an in-memory byte snapshot, with these arguments:
# -PackageDirectory <package-directory> -ExpectedManifestSha256 <reviewed-digest>
# Do not elevate a mutable script path or reread it after checking its digest.

# Configured owner, ordinary unelevated shell:
python scripts/credential_host.py profiles
python scripts/credential_host.py initialize <profile-id>
python scripts/credential_host.py entry <profile-id> --kind api_key --service Example --account Work --origin https://approved.example
python scripts/verify_credential_host.py <profile-id> --owner-id <reviewed-host-json-owner-id>
```

No source value is accepted as a CLI flag; enter it only in the native form.
The package starts with Personal/Work profiles and the fixed model/integration
helper catalog in `catalog.py`. Provider operations are installed as reviewed
helper descriptors; requesters cannot provide authenticated URLs.
An operator may pass `--helpers-file <reviewed-json>` at build time to seal fixed
HTTPS descriptors into this package; this replaces the entire default catalog.
The consumer cannot change them. The --tenant-origin build option seals a Jira
or PostHog tenant origin. Catalog and discovery pages are bounded by serialized
frame size; response chunks account for Unicode escaping. JSON/SSE/media helpers
run as cancellable jobs so the control pipe remains available. Explicit lock
resets all profiles/workers; idle lock cancels that profile's active jobs.
The post-install verifier launches only synthetic code, checks actual token,
scratch read/write/delete, snapshot-write denial, vault-file/key access, SYSTEM
process memory, actual network denial, empty
capabilities, child creation, management rejection and clean environment,
and returns booleans through `program_result`. It does not inspect any saved
credential value. This verifier remains unrun while the service is uninstalled.

Only scratch receives an inheritable Low mandatory integrity label. Source
snapshots, runtime and vault remain protected. Full launch teardown runs on
lease expiry independently of RPC traffic; helper work is also cancelled when
the controller dies or its consumer exits during an operation.

Settings > Credentials (or `scripts/credential_host.py action_profile_set UUID`)
selects the protected service preference for generic credential-isolated actions
after native owner consent. Omit the UUID to disable. `action_profile` reads only
this preference. No settings/profile-bundle import can select it.

## Acceptance record

Before deployment: Python policy tests, real non-elevated peer/token and
squatting-pipe tests, native C# compilation and PowerShell syntax validation
pass. `verify_credential_host.py` requires installation plus a human response
to the native Windows prompt. **Its installed execution has not yet passed in
this session.** Also verify secure consent decline/wrong-owner behavior,
cross-launch grants, vault key access denial, helper use, lock/suspend teardown,
and stop/cancellation on the installed service before release.

Current synthetic validation and provider/migration coverage are recorded in
[consumer implementation and release status](credential-manager-consumers.md).
Previous CM-03 package/test records predate the consumer changes and are not
acceptance evidence for this version. Do not install the obsolete v4 package.

Existing access/refresh tokens, cookies, browser profiles and session IDs retain
their current owners and locations. This change creates no duplicate token store.
No live source migration or service installation has been performed.

Windows API references:
[AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation),
[process security attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[secure native credential prompt](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-creduipromptforwindowscredentialsw),
[named-pipe security](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights),
[mandatory integrity control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control),
[label security information](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information).
