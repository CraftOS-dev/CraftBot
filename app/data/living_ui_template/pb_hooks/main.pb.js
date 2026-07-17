/// <reference path="../pb_data/types.d.ts" />
/**
 * Custom backend endpoints — YOUR app logic beyond CRUD.
 *
 * PocketBase already provides full CRUD for every collection in
 * config/schema.json (list/filter/sort/create/update/delete + realtime)
 * — NEVER write CRUD here. Add routes ONLY for multi-record
 * transactions, computed aggregations, and domain verbs.
 *
 * Rules (PocketBase JS hooks run in an embedded JS VM — goja):
 * - Plain JavaScript (ES5+). NO npm imports, NO node APIs; use the
 *   built-in globals: $app, $os, $http, $security (see
 *   pb_data/types.d.ts for the full ambient API).
 * - Query records: $app.findRecordsByFilter("cards", "position > 0", "-created", 100, 0)
 * - Create: new Record + $app.save(record) — or let the frontend use CRUD.
 * - Reply: return e.json(200, {...})
 * - AI calls: use callLLM below (bridges to the CraftBot host).
 *
 * Example — replace with your app's real endpoints:
 */

routerAdd("POST", "/api/custom/example-summary", (e) => {
  const items = $app.findRecordsByFilter("cards", "id != ''", "-created", 50, 0)
  return e.json(200, { count: items.length })
})

/** Call the CraftBot host LLM bridge. Returns "" on failure — degrade
 * gracefully, never crash the request. */
function callLLM(prompt, systemMessage) {
  try {
    const bridge = $os.getenv("CRAFTBOT_BRIDGE_URL")
    if (!bridge) return ""
    const res = $http.send({
      url: bridge + "/api/bridge/llm",
      method: "POST",
      body: JSON.stringify({ prompt: prompt, system_message: systemMessage || "" }),
      headers: {
        "content-type": "application/json",
        // The bridge rejects unauthenticated calls (401).
        authorization: "Bearer " + ($os.getenv("CRAFTBOT_BRIDGE_TOKEN") || ""),
      },
      timeout: 120,
    })
    return (res.json && res.json.content) || ""
  } catch (_) {
    return ""
  }
}
