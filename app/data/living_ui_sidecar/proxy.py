"""
Living UI Sidecar Proxy

A lightweight reverse proxy that sits in front of external apps,
injecting Living UI features (console capture, UI observation, health
checks, logging) without modifying the original app.

Usage:
    python proxy.py --app-port 3109 --proxy-port 3108

Architecture:
    Browser → This proxy (port 3108) → External app (port 3109)
                    ↓
              - Injects console/network capture into HTML responses
              - Injects UI snapshot + screenshot capture (agent observation)
              - Provides /health, /api/logs, /api/ui-snapshot,
                /api/ui-screenshot — the same A-layer contract native
                Living UIs get from pb_hooks/_craftbot.pb.js
              - Captures frontend logs to logs/frontend_console.log
              - Forwards everything else transparently

The observation flow mirrors the native template's UICapture: the injected
script watches the DOM (MutationObserver, debounced) and reports snapshots;
screenshots are captured on demand — the browser polls /__livingui/poll and
renders with a sidecar-served html2canvas when the agent has requested one.
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# Setup logging
LOG_DIR = (
    Path(__file__).parent.parent / "logs"
    if (Path(__file__).parent.parent / "logs").exists()
    else Path("logs")
)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sidecar.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("sidecar")

# Parse args
parser = argparse.ArgumentParser()
parser.add_argument(
    "--app-port", type=int, required=True, help="Port of the actual app"
)
parser.add_argument("--proxy-port", type=int, required=True, help="Port for this proxy")
args, _ = parser.parse_known_args()

APP_URL = f"http://localhost:{args.app_port}"
FRONTEND_LOG_PATH = LOG_DIR / "frontend_console.log"
HTML2CANVAS_PATH = Path(__file__).parent / "html2canvas.min.js"

# Observation timing (seconds). BROWSER_POLL_INTERVAL must match the
# injected script's poll cadence; POLL_ACTIVE_WINDOW is how recently a
# browser must have polled for a screenshot request to be worth waiting on.
BROWSER_POLL_INTERVAL = 2.0
POLL_ACTIVE_WINDOW = BROWSER_POLL_INTERVAL * 3
SCREENSHOT_WAIT = 12.0
SNAPSHOT_DEBOUNCE_MS = 1500

# Latest observation state reported by the injected capture script.
_OBS: Dict[str, Any] = {
    "snapshot": None,  # dict payload from the browser
    "screenshot": None,  # {"imageData", "width", "height", "timestamp"}
    "screenshot_taken_at": 0.0,  # monotonic time of last screenshot report
    "screenshot_requested": False,
    "last_poll": 0.0,  # monotonic time of last browser poll
}

# Console + observation capture script injected into HTML responses.
# Same-origin only; all endpoints are served by this sidecar.
CAPTURE_SCRIPT = (
    """
<script>
(function() {
  if (window.__livinguiCapture) return;
  window.__livinguiCapture = true;
  var BACKEND = window.location.origin;
  var buffer = [];
  var timer = null;
  var orig = { log: console.log.bind(console), warn: console.warn.bind(console), error: console.error.bind(console) };
  var origFetch = window.fetch.bind(window);
  var SKIP = ['/api/logs', '/__livingui/'];

  function skipUrl(url) {
    for (var i = 0; i < SKIP.length; i++) if (url.indexOf(SKIP[i]) !== -1) return true;
    return false;
  }

  function str(a) {
    if (typeof a === 'string') return a;
    if (a instanceof Error) return a.name + ': ' + a.message + (a.stack ? '\\n' + a.stack : '');
    try { var j = JSON.stringify(a); return j === '{}' ? String(a) : j; } catch(e) { return String(a); }
  }
  function args2str(a) { return Array.prototype.map.call(a, str).join(' '); }

  function add(level, msg) {
    buffer.push({ level: level, message: msg.slice(0, 5000), timestamp: new Date().toISOString() });
    if (buffer.length >= 20) flush();
    else if (!timer) timer = setTimeout(flush, 2000);
  }

  function flush() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!buffer.length) return;
    var entries = buffer; buffer = [];
    origFetch(BACKEND + '/api/logs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entries: entries })
    }).catch(function() {});
  }

  console.log = function() { orig.log.apply(console, arguments); add('log', args2str(arguments)); };
  console.warn = function() { orig.warn.apply(console, arguments); add('warn', args2str(arguments)); };
  console.error = function() { orig.error.apply(console, arguments); add('error', args2str(arguments)); };

  window.addEventListener('error', function(e) { add('error', 'Unhandled: ' + e.message); });
  window.addEventListener('unhandledrejection', function(e) { add('error', 'Unhandled rejection: ' + e.reason); });

  window.fetch = function(input, init) {
    var method = (init && init.method) || 'GET';
    var url = typeof input === 'string' ? input : (input instanceof URL ? input.toString() : input.url);
    if (skipUrl(url)) return origFetch(input, init);
    var t0 = performance.now();
    return origFetch(input, init).then(function(resp) {
      var ms = Math.round(performance.now() - t0);
      add(resp.status >= 400 ? 'error' : 'network', method + ' ' + url + ' → ' + resp.status + ' (' + ms + 'ms)');
      return resp;
    }).catch(function(err) {
      add('error', method + ' ' + url + ' → FAILED: ' + (err && err.message || err));
      throw err;
    });
  };

  window.addEventListener('beforeunload', flush);

  // ── UI snapshot capture (agent observation) ─────────────────────────
  var lastSig = '';
  var snapTimer = null;

  function visibleText() {
    var out = [];
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    var node;
    while ((node = walker.nextNode()) && out.length < 400) {
      var t = node.textContent.replace(/\\s+/g, ' ').trim();
      if (!t) continue;
      var el = node.parentElement;
      if (!el || el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'NOSCRIPT') continue;
      if (el.offsetParent === null && el.tagName !== 'BODY') continue;
      out.push(t.slice(0, 200));
    }
    return out;
  }

  function inputValues() {
    var out = {};
    var els = document.querySelectorAll('input, textarea, select');
    for (var i = 0; i < els.length && i < 100; i++) {
      var el = els[i];
      if (el.type === 'password') continue;
      var key = el.name || el.id || el.placeholder || (el.tagName.toLowerCase() + '_' + i);
      var val = el.type === 'checkbox' || el.type === 'radio' ? el.checked : el.value;
      if (typeof val === 'string') val = val.slice(0, 500);
      out[key] = val;
    }
    return out;
  }

  function buildSnapshot() {
    return {
      htmlStructure: document.body.outerHTML.slice(0, 60000),
      visibleText: visibleText(),
      inputValues: inputValues(),
      currentView: window.location.pathname + window.location.hash,
      viewport: { width: window.innerWidth, height: window.innerHeight,
                  scrollX: window.scrollX, scrollY: window.scrollY },
      title: document.title,
      timestamp: new Date().toISOString()
    };
  }

  function sendSnapshot() {
    try {
      var snap = buildSnapshot();
      var sig = snap.htmlStructure.length + '|' + snap.visibleText.length + '|' + snap.currentView;
      if (sig === lastSig) return;
      lastSig = sig;
      origFetch(BACKEND + '/__livingui/snapshot-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(snap)
      }).catch(function() {});
    } catch (e) { /* observation must never break the app */ }
  }

  function scheduleSnapshot() {
    if (snapTimer) clearTimeout(snapTimer);
    snapTimer = setTimeout(sendSnapshot, """
    + str(SNAPSHOT_DEBOUNCE_MS)
    + """);
  }

  if (document.readyState === 'complete') scheduleSnapshot();
  else window.addEventListener('load', scheduleSnapshot);
  try {
    new MutationObserver(scheduleSnapshot).observe(document.body,
      { childList: true, subtree: true, attributes: true, characterData: true });
  } catch (e) {}
  document.addEventListener('input', scheduleSnapshot, true);

  // ── On-demand screenshot (html2canvas served by the sidecar) ────────
  var h2cLoading = null;
  function ensureHtml2canvas() {
    if (window.html2canvas) return Promise.resolve();
    if (h2cLoading) return h2cLoading;
    h2cLoading = new Promise(function(resolve, reject) {
      var s = document.createElement('script');
      s.src = BACKEND + '/__livingui/html2canvas.js';
      s.onload = function() { resolve(); };
      s.onerror = function() { h2cLoading = null; reject(new Error('html2canvas load failed')); };
      document.head.appendChild(s);
    });
    return h2cLoading;
  }

  var shooting = false;
  function takeScreenshot() {
    if (shooting) return;
    shooting = true;
    ensureHtml2canvas().then(function() {
      return window.html2canvas(document.body, { logging: false, useCORS: true });
    }).then(function(canvas) {
      var imageData = canvas.toDataURL('image/png').split(',')[1];
      return origFetch(BACKEND + '/__livingui/screenshot-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ imageData: imageData, width: canvas.width, height: canvas.height,
                               timestamp: new Date().toISOString() })
      });
    }).catch(function(e) {
      add('warn', '[livingui] screenshot failed: ' + (e && e.message || e));
    }).then(function() { shooting = false; });
  }

  setInterval(function() {
    origFetch(BACKEND + '/__livingui/poll').then(function(r) { return r.json(); })
      .then(function(cmd) { if (cmd && cmd.screenshot) takeScreenshot(); })
      .catch(function() {});
  }, """
    + str(int(BROWSER_POLL_INTERVAL * 1000))
    + """);
})();
</script>
"""
)

# FastAPI app
app = FastAPI(title="Living UI Sidecar Proxy")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

http_client = httpx.AsyncClient(base_url=APP_URL, timeout=30, follow_redirects=True)


# ── Living UI endpoints (handled by sidecar, not forwarded) ──────────


@app.get("/health")
async def health():
    """Health check — verifies both sidecar and app are running."""
    try:
        resp = await http_client.get("/", timeout=5)
        app_ok = resp.status_code < 500
    except Exception:
        app_ok = False
    return {
        "status": "healthy" if app_ok else "degraded",
        "sidecar": "ok",
        "app": "ok" if app_ok else "down",
    }


class LogEntry(BaseModel):
    level: str
    message: str
    timestamp: Optional[str] = None


class LogBatch(BaseModel):
    entries: List[LogEntry]


@app.post("/api/logs")
async def capture_logs(data: LogBatch):
    """Receive frontend console logs from the injected capture script."""
    with open(FRONTEND_LOG_PATH, "a", encoding="utf-8") as f:
        for entry in data.entries:
            ts = entry.timestamp or datetime.utcnow().isoformat()
            f.write(f"{ts} | {entry.level.upper():<7} | {entry.message}\n")
    return {"status": "ok", "count": len(data.entries)}


# ── Agent observation (same contract as the native A-layer) ──────────


@app.get("/__livingui/html2canvas.js")
async def serve_html2canvas():
    """Serve the vendored html2canvas for on-demand screenshots."""
    if not HTML2CANVAS_PATH.exists():
        return JSONResponse({"error": "html2canvas not vendored"}, status_code=404)
    return FileResponse(
        HTML2CANVAS_PATH,
        media_type="application/javascript",
        headers={"Cache-Control": "max-age=86400"},
    )


@app.get("/__livingui/poll")
async def browser_poll():
    """Lightweight command channel: the injected script polls this."""
    _OBS["last_poll"] = time.monotonic()
    return {"screenshot": bool(_OBS["screenshot_requested"])}


@app.post("/__livingui/snapshot-report")
async def snapshot_report(request: Request):
    """Store the latest UI snapshot reported by the browser."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    if isinstance(payload, dict):
        payload.setdefault("timestamp", datetime.utcnow().isoformat())
        _OBS["snapshot"] = payload
    return {"status": "ok"}


@app.post("/__livingui/screenshot-report")
async def screenshot_report(request: Request):
    """Store the latest screenshot reported by the browser."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    if isinstance(payload, dict) and payload.get("imageData"):
        payload.setdefault("timestamp", datetime.utcnow().isoformat())
        _OBS["screenshot"] = payload
        _OBS["screenshot_taken_at"] = time.monotonic()
        _OBS["screenshot_requested"] = False
    return {"status": "ok"}


@app.get("/api/ui-snapshot")
async def ui_snapshot():
    """Latest UI snapshot — mirrors the native /api/ui-snapshot contract."""
    if _OBS["snapshot"] is None:
        return JSONResponse(
            {
                "error": "no snapshot captured yet — open the app in the "
                "browser (the Living UI tab) so the capture script can run"
            },
            status_code=404,
        )
    return _OBS["snapshot"]


@app.get("/api/ui-screenshot")
async def ui_screenshot():
    """On-demand screenshot — requests a fresh capture from a connected
    browser and waits briefly; falls back to the last capture."""
    requested_at = time.monotonic()
    _OBS["screenshot_requested"] = True

    browser_active = (requested_at - _OBS["last_poll"]) < POLL_ACTIVE_WINDOW
    if browser_active:
        deadline = requested_at + SCREENSHOT_WAIT
        while time.monotonic() < deadline:
            if _OBS["screenshot_taken_at"] >= requested_at:
                return _OBS["screenshot"]
            await asyncio.sleep(0.25)

    if _OBS["screenshot"] is not None:
        stale = dict(_OBS["screenshot"])
        stale["stale"] = True
        return stale
    return JSONResponse(
        {
            "error": "no screenshot captured yet — open the app in the "
            "browser (the Living UI tab) so the capture script can run"
        },
        status_code=404,
    )


# ── Reverse proxy (forwards everything else to the app) ──────────────


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
)
async def proxy(request: Request, path: str):
    """Forward all requests to the actual app, inject capture script into HTML responses."""
    # Build the proxied URL
    url = f"/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    # Forward headers (skip host)
    headers = dict(request.headers)
    headers.pop("host", None)

    try:
        body = await request.body()
        resp = await http_client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body if body else None,
        )
    except httpx.ConnectError:
        return JSONResponse({"error": "App not responding"}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    # Check if response is HTML — inject capture script
    content_type = resp.headers.get("content-type", "")
    response_body = resp.content

    if "text/html" in content_type:
        html = response_body.decode("utf-8", errors="replace")
        # Inject capture script before </body> or at end
        if "</body>" in html.lower():
            idx = html.lower().rfind("</body>")
            html = html[:idx] + CAPTURE_SCRIPT + html[idx:]
        else:
            html += CAPTURE_SCRIPT
        response_body = html.encode("utf-8")

    # Build response with original headers
    response_headers = dict(resp.headers)
    response_headers.pop("content-length", None)  # Will be recalculated
    response_headers.pop("content-encoding", None)  # We may have modified the content
    response_headers.pop("transfer-encoding", None)

    return Response(
        content=response_body,
        status_code=resp.status_code,
        headers=response_headers,
    )


if __name__ == "__main__":
    import uvicorn

    logger.info(
        f"Starting sidecar proxy: localhost:{args.proxy_port} → localhost:{args.app_port}"
    )
    uvicorn.run(app, host="0.0.0.0", port=args.proxy_port, log_level="warning")
