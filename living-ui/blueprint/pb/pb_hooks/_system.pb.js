/// <reference path="../pb_data/types.d.ts" />
/**
 * SYSTEM HOOKS — managed by tooling, never edited by agents (spec P1).
 * - origin guard        CORS + frame-ancestors (spec A2APP-PLAN Phase 1 A1/A2)
 * - GET  /api/_ops      operations manifest discovery (spec O4)
 * - POST /api/_console  frontend console relay sink (spec K8/D12)
 * (Health is PocketBase's built-in /api/health.)
 */

/**
 * ORIGIN GUARD.
 *
 * PocketBase answers every request with `Access-Control-Allow-Origin: *`, and
 * these apps ship with open collection rules because they bind loopback. The
 * assumption that "loopback is safe" is wrong: loopback is reachable by every
 * page the user visits, so with a wildcard ACAO any website could read AND
 * write the user's data — verified against a running app from a foreign origin.
 * This is the same class as the Jan and drawio-mcp advisories.
 *
 * CORS is enforced by the browser, so the fix is the HEADER, not the body: a
 * page from evil.example no longer receives an ACAO it can use, and its
 * preflight for a destructive route is no longer approved. Direct clients
 * (curl, the CLI, an agent) are unaffected — they were never the threat.
 *
 * Policy: loopback origins only. That covers the app's own frontend
 * (same-origin) and the CraftBot shell, and excludes the public internet.
 *
 * NOTE FOR EDITORS: hook callbacks run in isolated VMs that CANNOT see this
 * file's scope — a callback referencing a const or function declared out here
 * dies with "ReferenceError: <name> is not defined". Everything below is
 * therefore inlined per callback, deliberately, including the origin pattern.
 */

routerUse((e) => {
  // Must run BEFORE e.next(): headers are flushed with the first body byte, so
  // post-next mutation is a no-op. PocketBase's own setters run before user
  // middleware, so changes made here win.
  const ALLOWED_ORIGIN = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/;
  var headers = e.response.header();
  var origin = '';
  try {
    origin = String(e.request.header.get('Origin') || '');
  } catch {
    origin = '';
  }

  // Framing: replace the blanket X-Frame-Options delete (which allowed ANY
  // site to frame the app) with a policy that names who may.
  headers.del('X-Frame-Options');
  headers.set(
    'Content-Security-Policy',
    "frame-ancestors 'self' http://127.0.0.1:* http://localhost:*"
  );

  if (origin === '') return e.next(); // not a browser cross-origin request

  if (ALLOWED_ORIGIN.test(origin)) {
    headers.set('Access-Control-Allow-Origin', origin);
    headers.set('Vary', 'Origin');
    return e.next();
  }

  // Foreign origin: withhold every CORS grant, so the browser refuses to
  // expose the response. This is what stops a drive-by READ.
  headers.del('Access-Control-Allow-Origin');
  headers.del('Access-Control-Allow-Methods');
  headers.del('Access-Control-Allow-Headers');
  headers.del('Access-Control-Allow-Credentials');
  headers.del('Access-Control-Expose-Headers');

  // Withholding headers is NOT enough for writes. PocketBase answers the
  // OPTIONS preflight itself, before user middleware runs, so it still returns
  // `Access-Control-Allow-Origin: *` and the browser goes on to send the real
  // request — the response is unreadable, but the write already happened.
  // So mutating methods from a foreign origin are refused outright.
  var method = '';
  try {
    method = String(e.request.method || '').toUpperCase();
  } catch {
    method = '';
  }
  if (method === 'POST' || method === 'PATCH' || method === 'PUT' || method === 'DELETE') {
    return e.json(403, {
      ok: false,
      error: 'forbidden origin: ' + origin,
      hint: 'This app only accepts writes from loopback origins.',
    });
  }
  return e.next();
});

/**
 * OPS AUTH GUARD (spec A2APP-PLAN Phase 1 A7).
 *
 * Op routes execute through `e.app.*`, which bypasses PocketBase's API rules —
 * the layer REQUIREMENTS B6 designates as the security boundary. In a
 * multi-user app that is a hole big enough to defeat the app's own rules:
 * crm-system sets `@request.auth.id != ""` on all 15 collections and then
 * exposes an unauthenticated arbitrary-recipient Gmail send at
 * POST /api/ops/emails/send.
 *
 * Enforcing here rather than in each app's ops.pb.js means it cannot be
 * forgotten when an agent adds a route, and it ships with kit-sync.
 *
 * `authMode: none` apps are unaffected — they have no principal to check, and
 * the origin guard above is what protects them.
 */
routerUse((e) => {
  var path = '';
  try {
    path = String((e.request.url && e.request.url.path) || '');
  } catch {
    return e.next();
  }
  if (path.indexOf('/api/ops/') !== 0) return e.next();

  var authMode = 'none';
  try {
    var manifest = JSON.parse(
      toString($os.readFile($filepath.join(__hooks, '..', '..', 'manifest.json')))
    );
    authMode = String(manifest.authMode || 'none');
  } catch {
    authMode = 'none';
  }
  if (authMode !== 'multi-user') return e.next();

  var authed = false;
  try {
    if (e.auth) authed = true;
  } catch {
    /* fall through */
  }
  if (!authed) {
    try {
      var info = e.requestInfo();
      if (info && info.auth) authed = true;
    } catch {
      /* fall through */
    }
  }
  if (!authed) {
    return e.json(401, {
      ok: false,
      error: 'authentication required',
      hint: 'This app is multi-user; operations require a signed-in principal.',
    });
  }
  return e.next();
});

/**
 * AGENT TOKEN (spec A2APP-PLAN Phase 2 C4).
 *
 * A non-browser client that writes must present the project's agent token.
 * The app's own frontend does not need it: browsers always send `Origin` on a
 * write, and a loopback `Origin` is already trusted by the guard above. So the
 * rule is precisely "programmatic callers carry a credential", which is what
 * makes handing access to a third-party agent a deliberate act.
 *
 * Not a defence against local processes — anything running as this user can
 * read the 0600 file. That is the correct model for a loopback app (Home
 * Assistant and Obsidian's local API work the same way); what it buys is a
 * real credential to hand out, and the precondition for tightening collection
 * rules and for remote access later.
 */
routerUse((e) => {
  var method = '';
  var path = '';
  var origin = '';
  try {
    method = String(e.request.method || '').toUpperCase();
    path = String((e.request.url && e.request.url.path) || '');
    origin = String(e.request.header.get('Origin') || '');
  } catch {
    return e.next();
  }
  if (method !== 'POST' && method !== 'PATCH' && method !== 'PUT' && method !== 'DELETE') {
    return e.next();
  }
  if (path.indexOf('/api/collections/') !== 0 && path.indexOf('/api/ops/') !== 0) {
    return e.next();
  }
  // Browser traffic: already constrained to loopback origins by the guard.
  if (origin !== '') return e.next();
  // PocketBase's own auth flows must stay reachable (sign-in, refresh).
  if (path.indexOf('/auth-') > 0 || path.indexOf('/request-') > 0) return e.next();

  var expected = '';
  try {
    expected = toString($os.readFile($filepath.join(__hooks, '..', '..', '.agent-token'))).trim();
  } catch {
    expected = '';
  }
  if (expected === '') return e.next(); // no token provisioned — do not lock the app out

  var presented = '';
  try {
    presented = String(e.request.header.get('X-LUI-Token') || '').trim();
  } catch {
    presented = '';
  }
  if (presented !== expected) {
    return e.json(401, {
      ok: false,
      error: 'agent token required',
      hint: 'Send X-LUI-Token: <contents of the project .agent-token file> on writes.',
    });
  }
  return e.next();
});

/**
 * RATE LIMITS (spec A2APP-PLAN Phase 1 A3).
 *
 * PocketBase ships with `rateLimits.enabled: false`. These apps bind loopback
 * with open rules, so an unbounded request rate is both a local-DoS surface
 * and free rein for anything brute-forcing record ids or auth. Applied at
 * bootstrap so a fresh pb_data gets it without a migration.
 *
 * Limits are deliberately loose — high enough that a UI, an agent doing bulk
 * work, and the CLI never notice, low enough that a runaway loop or a scan
 * does. Tighten per app if needed.
 */
onBootstrap((e) => {
  e.next();
  try {
    const settings = $app.settings();
    if (settings.rateLimits.enabled) return;
    settings.rateLimits.enabled = true;
    settings.rateLimits.rules = [
      { label: '*:auth', maxRequests: 30, duration: 60 },
      { label: '/api/collections/', maxRequests: 1200, duration: 60 },
      { label: '/api/ops/', maxRequests: 300, duration: 60 },
      { label: '/api/_console', maxRequests: 120, duration: 60 },
    ];
    $app.save(settings);
    console.log('[system] rate limits enabled');
  } catch (err) {
    // Never block boot on this.
    console.log('[system] could not enable rate limits: ' + err);
  }
});

routerAdd('GET', '/api/_ops', (e) => {
  const path = $filepath.join(__hooks, '..', '..', 'operations.json');
  const raw = toString($os.readFile(path));
  return e.json(200, JSON.parse(raw));
});

routerAdd('POST', '/api/_console', (e) => {
  // Unauthenticated arbitrary disk write otherwise: any page could fill the
  // user's disk 50 x 4000 chars at a time. Same-origin (the app's own
  // frontend) or a loopback tool only. Inlined per the note at the top.
  const ALLOWED_ORIGIN = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/;
  let origin = '';
  try {
    origin = String(e.request.header.get('Origin') || '');
  } catch {
    origin = '';
  }
  if (origin !== '' && !ALLOWED_ORIGIN.test(origin)) {
    return e.json(403, { ok: false, error: 'forbidden origin' });
  }

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
  // Cap the file so an unbounded relay cannot grow without limit.
  if (existing.length > 2 * 1024 * 1024) existing = existing.slice(-1024 * 1024);

  const lines = entries
    .slice(0, 50)
    .map((x) => JSON.stringify({ ts: x.ts, level: x.level, message: String(x.message).slice(0, 4000) }))
    .join('\n');
  $os.writeFile(logFile, existing + lines + '\n', 0o644);
  return e.json(200, { ok: true });
});
