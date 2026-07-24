/// <reference path="../pb_data/types.d.ts" />
/**
 * SYSTEM HOOKS — managed by tooling, never edited by agents (spec P1).
 * - GET  /api/_ops      operations manifest discovery (spec O4)
 * - POST /api/_console  frontend console relay sink (spec K8/D12)
 * (Health is PocketBase's built-in /api/health.)
 */

// Allow embedding in the CraftBot shell: PocketBase sets
// X-Frame-Options: sameorigin by default, which blocks the host iframe.
// Loopback-bound local apps are safe to frame.
routerUse((e) => {
  // Must run BEFORE e.next(): headers are flushed with the first body byte,
  // so post-next deletion is a no-op. PB's own SAMEORIGIN setter runs before
  // user middleware, so a pre-next delete removes it for good.
  e.response.header().del('X-Frame-Options');
  return e.next();
});

routerAdd('GET', '/api/_ops', (e) => {
  const path = $filepath.join(__hooks, '..', '..', 'operations.json');
  const raw = toString($os.readFile(path));
  return e.json(200, JSON.parse(raw));
});

routerAdd('POST', '/api/_console', (e) => {
  const body = e.requestInfo().body;
  const entries = Array.isArray(body?.entries) ? body.entries : [];
  if (entries.length === 0) return e.json(200, { ok: true });

  const logsDir = $filepath.join(__hooks, '..', '..', 'logs');
  $os.mkdirAll(logsDir, 0o755);
  const logFile = $filepath.join(logsDir, 'frontend_console.log');

  let existing = '';
  try {
    existing = toString($os.readFile(logFile));
  } catch {
    // first write
  }
  const lines = entries
    .slice(0, 50)
    .map((x) => JSON.stringify({ ts: x.ts, level: x.level, message: String(x.message).slice(0, 4000) }))
    .join('\n');
  $os.writeFile(logFile, existing + lines + '\n', 0o644);
  return e.json(200, { ok: true });
});
