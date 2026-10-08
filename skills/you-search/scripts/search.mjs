#!/usr/bin/env node

function usage() {
  console.error(`Usage: search.mjs "query" [-n 5]`);
  process.exit(2);
}

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === "-h" || args[0] === "--help") usage();

const query = args[0];
let n = 5;

for (let i = 1; i < args.length; i++) {
  if (args[i] === "-n" && i + 1 < args.length) {
    n = Math.max(1, Math.min(parseInt(args[i + 1], 10) || 5, 20));
    i++;
  } else {
    usage();
  }
}

const apiKey = (process.env.YDC_API_KEY ?? "").trim();
const endpoint = apiKey ? "https://api.you.com/mcp" : "https://api.you.com/mcp?profile=free";
const headers = {
  "Content-Type": "application/json",
  Accept: "application/json, text/event-stream",
  ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
};

async function readMcpMessage(response) {
  // The MCP endpoint answers with either plain JSON or an SSE stream.
  // Return the first JSON-RPC message carrying a result — progress
  // notifications and other events are skipped.
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream")) {
    const text = await response.text();
    for (const frame of text.split("\n\n")) {
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data:")) continue;
        try {
          const msg = JSON.parse(line.slice(5).trim());
          if (msg && msg.result !== undefined) return msg;
        } catch {
          // not a complete JSON frame — skip
        }
      }
    }
    throw new Error("No JSON-RPC result found in You.com MCP response");
  }
  return await response.json();
}

async function post(body) {
  const resp = await fetch(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(60000),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`You.com MCP request failed (${resp.status}): ${text}`);
  }
  return resp;
}

try {
  // 1. initialize
  const initResp = await post({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "craftbot-you-search", version: "1.0.0" },
    },
  });
  await readMcpMessage(initResp);

  const sessionId = initResp.headers.get("mcp-session-id");
  if (sessionId) headers["Mcp-Session-Id"] = sessionId;

  // 2. notifications/initialized
  const readyResp = await post({
    jsonrpc: "2.0",
    method: "notifications/initialized",
  });
  await readyResp.text().catch(() => "");

  // 3. tools/call you-search
  const callResp = await post({
    jsonrpc: "2.0",
    id: 2,
    method: "tools/call",
    params: {
      name: "you-search",
      arguments: { query, count: n },
    },
  });
  const msg = await readMcpMessage(callResp);
  const result = msg.result;

  if (!result || result.isError) {
    throw new Error(`You.com you-search failed: ${JSON.stringify(result?.content ?? result)}`);
  }

  let results = [];
  for (const item of result.content ?? []) {
    if (item.type !== "text") continue;
    try {
      const data = JSON.parse(item.text);
      results = data?.results?.web ?? [];
      break;
    } catch {
      // not a JSON payload — skip
    }
  }

  if (results.length === 0) {
    console.error("No results found.");
    process.exit(0);
  }

  console.log("## Sources\n");

  for (const r of results.slice(0, n)) {
    const title = String(r?.title ?? "").trim();
    const url = String(r?.url ?? "").trim();
    const snippet = String(r?.description ?? r?.snippets?.[0] ?? "").trim();

    if (!title || !url) continue;
    console.log(`- **${title}**`);
    console.log(`  ${url}`);
    if (snippet) {
      console.log(`  ${snippet.slice(0, 300)}${snippet.length > 300 ? "..." : ""}`);
    }
    console.log();
  }
} catch (e) {
  console.error(`Error: ${e.message}`);
  process.exit(1);
}
