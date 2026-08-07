# Frontend rules that keep verification green (copy-adapt)
- Call your own API RELATIVELY: fetch('/api/ops/refresh') — never absolute
  http://127.0.0.1:<port> self-URLs (ports change; restarts race).
- No mutation ops on mount: refresh is user-triggered; data arrives via the
  kit's realtime `useCollection` — never poll, never reload.
- Load-time reads must survive an EMPTY database (first-paint console errors
  fail the launch verifier).
- Missing API values render as an honest empty/offline state — never `|| 0`
  defaults (a zero you invent is a lie that passes review).
