/// <reference path="../pb_data/types.d.ts" />
/**
 * CraftBot system routes (SYSTEM-MANAGED — do not edit).
 *
 * The platform's agent-awareness machinery (state persistence, UI
 * snapshots, action bridge) talks to these endpoints; they existed on the
 * old Python backend and are served here by PocketBase's JS hooks so the
 * frontend services keep working unchanged.
 */

// Whole-blob app state — the exact contract services/ApiService.ts uses:
//   GET  /api/state            -> the full state object
//   PUT  /api/state   {data}   -> merge data into state, return the merged state
//   POST /api/state/replace {data} -> replace state entirely, return it
//   DELETE /api/state          -> clear state
// NOTE: PocketBase runs each hook handler in an ISOLATED JSVM runtime — a
// handler CANNOT reference module-scope helpers/vars, so every route below
// inlines its file path + read/merge logic. Do not factor these out.
routerAdd("GET", "/api/state", (e) => {
  const path = $app.dataDir() + "/craftbot_state.json"
  try {
    return e.json(200, JSON.parse(toString($os.readFile(path))) || {})
  } catch (_) {
    return e.json(200, {})
  }
})

routerAdd("PUT", "/api/state", (e) => {
  const path = $app.dataDir() + "/craftbot_state.json"
  const body = e.requestInfo().body || {}
  const updates = body.data !== undefined ? body.data : body
  let merged = {}
  try { merged = JSON.parse(toString($os.readFile(path))) || {} } catch (_) {}
  for (const k in updates) merged[k] = updates[k]
  $os.writeFile(path, JSON.stringify(merged), 0o644)
  return e.json(200, merged)
})

routerAdd("POST", "/api/state/replace", (e) => {
  const path = $app.dataDir() + "/craftbot_state.json"
  const body = e.requestInfo().body || {}
  const next = (body.data !== undefined ? body.data : body) || {}
  $os.writeFile(path, JSON.stringify(next), 0o644)
  return e.json(200, next)
})

routerAdd("DELETE", "/api/state", (e) => {
  $os.writeFile($app.dataDir() + "/craftbot_state.json", "{}", 0o644)
  return e.json(200, { status: "ok" })
})

// Console log sink — services/ConsoleCapture.ts POSTs { entries: [...] }.
routerAdd("POST", "/api/logs", (e) => {
  try {
    const body = e.requestInfo().body || {}
    const entries = body.entries || []
    const path = $app.dataDir() + "/craftbot_console.jsonl"
    let prev = ""
    try { prev = toString($os.readFile(path)) } catch (_) {}
    let out = prev
    for (let i = 0; i < entries.length; i++) out += JSON.stringify(entries[i]) + "\n"
    $os.writeFile(path, out, 0o644)
  } catch (_) {}
  return e.json(200, { status: "ok" })
})

// UI snapshot — the observation channel validators read
routerAdd("POST", "/api/ui-snapshot", (e) => {
  const body = e.requestInfo().body
  $os.writeFile($app.dataDir() + "/craftbot_ui_snapshot.json", JSON.stringify(body), 0o644)
  return e.json(200, { status: "ok" })
})

routerAdd("GET", "/api/ui-snapshot", (e) => {
  try {
    const raw = toString($os.readFile($app.dataDir() + "/craftbot_ui_snapshot.json"))
    return e.json(200, JSON.parse(raw))
  } catch (_) {
    return e.json(200, {})
  }
})

// Action bridge — frontend posts user/agent action events
routerAdd("POST", "/api/action", (e) => {
  const body = e.requestInfo().body
  const path = $app.dataDir() + "/craftbot_actions.jsonl"
  let prev = ""
  try { prev = toString($os.readFile(path)) } catch (_) {}
  $os.writeFile(path, prev + JSON.stringify(body) + "\n", 0o644)
  return e.json(200, { status: "ok" })
})

// Legacy health path (PB's own is /api/health)
routerAdd("GET", "/health", (e) => {
  return e.json(200, { status: "healthy", engine: "pocketbase" })
})
