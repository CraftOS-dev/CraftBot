# CM-02: shared encrypted profile vault

The host storage implementation is in `app/credentials/`. It is not exposed to
agents, Agent Apps, browser WebSockets, or integration/model clients. Default
owner verification refuses unlock; CM-03 must provide verified owner authority
and OS-enforced helper/caller isolation before consumer access can be enabled.

## Storage and ownership

`ProfileVault` receives an explicit host-owned storage root, `VaultOwner`, and
`VaultProfile`. It never scans, imports, renames or defaults to the existing
`.credentials` directory. The profile snapshot is stored at:

```text
<root>/<owner UUID>/<profile UUID>/vault.sqlite3
```

SQLite holds only current/previous Fernet-authenticated encrypted JSON blobs.
Owner/OS identity, profile metadata, record metadata and all secret fields are
inside the encrypted document; each decode checks owner/profile identity and
format. Each profile has an independent key. Multiple accounts and duplicate
display labels use independent UUIDs, not implicit upserts.

SQLite replaces the browser's whole-file read/modify/replace implementation for
the shared format: `BEGIN IMMEDIATE` serializes cross-process writes, each save
commits the new ciphertext and previous ciphertext atomically, and FULL
synchronization is enabled. Journals and previous snapshots contain encrypted
data only. Connections close on every path, including transaction failures.
There is no decrypted document cache. Owner/profile metadata survives restart
inside the protected snapshot, but owner enrollment/profile discovery and the
CM-01 directory's persistence are supplied by the installed protected host.

`WindowsCredentialKeyStore` stores the profile's encryption key in Windows
Credential Manager, never beside the DB. It reads only the exact target:
`CraftBot/Vault/v1/<owner UUID>/<profile UUID>`. No enumeration, login-password
access, raw-file fallback, or automatic key deletion is provided. pywin32's
generic credential strings use UTF-16LE; the adapter decodes to the original
ASCII Fernet key internally. Device/profile loss requires reconnect or re-entry;
there is no portable export.

The Windows key and ACL adapters use the existing Windows pywin32 dependency.
Other platforms fail closed until a secure key adapter is implemented; tests may
inject a test-only in-memory key facility. Windows vault directories/files have
protected owner/SYSTEM DACLs. POSIX directories/files require owner-only 0700/0600
modes and correct ownership. Symlink/reparse-point vault paths are rejected;
the configured root's ancestors must themselves be trusted. Same-user hostile
code still requires the CM-03 OS/process boundary: these permissions and the OS
key facility do not claim to provide it by themselves.

## Lifecycle and owner operations

- Construction/status do not create files, read OS keys, or unlock anything.
- `initialize()` is an explicit verified-owner action. It cannot replace an
  existing snapshot or silently turn a corrupt/empty existing schema into a new
  vault. A failed first transaction can retry with the same OS key; keys are
  never regenerated to hide a missing/decryption-failed vault.
- `unlock()` verifies the owner, loads the OS key, and validates the full
  encrypted snapshot before reporting READY. Missing key, decrypt/schema failure,
  wrong scope, missing backend, or unavailable verification fails closed.
- CRUD accepts login/API-key/manual-service-secret records. Secure owner entry
  wraps field dictionaries in `Secret` immediately; normal list/create/update
  results contain metadata only. There is no public secret-read/use method.
- Logins require username/password and explicit HTTPS origins. Stored origins
  preserve exact hosts, without `www` equivalence. Runtime destination/network
  authorization and browser-specific validation remain CM-03/05 responsibilities.
- Updates preserve the item UUID and increment its version, including metadata
  changes. Stale update/delete references fail; empty edit fields preserve saved
  values. Deletion affects vault data only.
- A real daemon timer locks after 15 minutes without owner activity. Reads/writes
  do not reset it. Only trusted owner UI activity can renew it. Explicit lock,
  idle expiry, backend/decrypt failure and close drop cached key-derived state;
  every unlock creates a fresh epoch for future capability binding.
- Host OS-lock/sleep/exit callbacks must call `lock()`/`close()`. Platform event
  registration and the live owner UI are not connected in this storage slice.
- Re-read the OS key on each operation to detect a removed/replaced key or backend
  outage while unlocked. Managed Python memory has no guaranteed zeroization.

Errors are stable codes without secret values, OS error text, or paths. Corrupt
snapshots are preserved and writes refused. Previous encrypted snapshots are
retained for a future explicit owner recovery flow; no automatic reset or
rollback, portable backup/export, grant/audit persistence, or migration is added.
Previous encrypted snapshots may contain replaced/deleted fields: removing an
item denies future use through the current vault, not forensic secure erasure.
Public storage operations discard inner traceback frames before raising sanitized
errors: `from None` alone does not hide exception values retained in context-manager
frames from diagnostic loggers. This boundary is covered by a diagnose-mode test.

## Legacy browser compatibility and unchanged state

The redacting `Secret` holder was extracted from `app/mini_browser/vault.py`
into `app/credentials/secrets.py`; the browser re-exports the same API. The
legacy browser format remains available for offline conversion. Subsequent work
replaces normal browser access with protected helpers and provides explicit
owner-run migration; see [current coverage](credential-manager-consumers.md).
No migration runs automatically and no live source file was migrated here.

Generated integration/model/subscription access/refresh/session tokens, browser
cookies/profiles and WhatsApp sessions are not moved. Token
refresh/client constructor/integration bridge changes belong to the consumer
phase documented separately. Locking or
deleting an item in this storage API does not disconnect any existing account.

## Validation

Tests use synthetic owner IDs, profiles, values and temporary directories.
Coverage includes encrypted CRUD/restart, profile/key separation, version
conflicts, metadata-only results, empty edit preservation, idle timer execution,
owner-only renewal, missing verification/keys/backends, corruption preservation,
unknown/wrong-scope documents, crash/failed-write rollback, explicit initial-save
retry, concurrent independent writers, encrypted previous snapshots and on-disk
leak scans. Token/session sentinel files remain byte-for-byte unchanged.

Windows tests verify protected DACLs and actual Credential Manager key/full-vault
restart round trips. Real smoke tests create only unique synthetic UUID targets
and remove those exact targets afterward. POSIX mode and symlink tests run where
supported. Legacy browser-vault tests check compatibility of the extracted
redacting holder; no real user credential files are accessed for validation.
