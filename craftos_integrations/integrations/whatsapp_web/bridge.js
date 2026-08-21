#!/usr/bin/env node
/**
 * CraftBot WhatsApp Bridge
 *
 * Standalone Node.js process that wraps whatsapp-web.js and communicates
 * with the Python agent via stdin/stdout JSON lines.
 *
 * Protocol:
 *   Python → Node (stdin):  JSON command per line
 *     { "id": "req_1", "cmd": "send_message", "args": { "to": "...", "text": "..." } }
 *
 *   Node → Python (stdout): JSON event/response per line
 *     { "type": "event", "event": "message", "data": { ... } }
 *     { "type": "response", "id": "req_1", "data": { ... } }
 *
 *   Logs go to stderr so they don't interfere with the JSON protocol.
 *
 * Lifecycle (session-durability redesign §2.4): all client state lives in
 * a ClientGeneration — one wweb.js client, its handlers, and its timers.
 * Events from a superseded/disposed generation are dropped at a single
 * gate, so an old generation can never destroy the live client or emit
 * stale events. The watchdog is phase-aware:
 *
 *   LAUNCH  (initialize → qr|authenticated): 90s — a genuine hang detector.
 *            On expiry: dispose + retry (bounded), then fatal exit.
 *   QR_WAIT (after qr): watchdog SUSPENDED. A human scanning a QR is not a
 *            hang; wweb.js refreshes the code itself, and the Python
 *            LinkFlow owns total-QR-time policy (recycle/timeout).
 *   INJECT  (authenticated → ready): 60s. On expiry: fatal error + clean
 *            exit — NO synthetic ready (a lying ready masks a dead receive
 *            path; the Python supervisor restarts us with backoff).
 *
 * The process never lingers in a broken state: unhandledRejection and
 * uncaughtException emit a fatal error event and exit(1) deliberately so
 * the Python supervisor sees the exit and applies backoff.
 */

const { Client, LocalAuth, MessageMedia, Location, Buttons, List, Poll } = require("whatsapp-web.js");
const qrcode = require("qrcode");
const path = require("path");
const readline = require("readline");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function log(...args) {
  process.stderr.write(`[WA-Bridge] ${args.join(" ")}\n`);
}

/** Send a JSON line to stdout (Python reads this). */
function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

/** Send an event to Python. */
function emitEvent(event, data = {}) {
  emit({ type: "event", event, data });
}

/** Send a command response to Python. */
function emitResponse(id, data = {}) {
  emit({ type: "response", id, data });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const AUTH_DIR = process.argv[2] || path.join(process.cwd(), ".credentials", "whatsapp_wwebjs_auth");

const LAUNCH_TIMEOUT_MS = parseInt(process.env.WA_BRIDGE_LAUNCH_TIMEOUT_MS || "", 10) || 90_000;
const INJECT_TIMEOUT_MS = parseInt(process.env.WA_BRIDGE_INJECT_TIMEOUT_MS || "", 10) || 60_000;
const MAX_LAUNCH_RETRIES = 2; // total attempts = MAX_LAUNCH_RETRIES + 1

log(`Auth directory: ${AUTH_DIR}`);

// ---------------------------------------------------------------------------
// WhatsApp Client
// ---------------------------------------------------------------------------

// We deliberately do NOT pin a webVersionCache. Pinning ties us to a
// snapshot from wppconnect-team/wa-version, which (a) prunes old entries
// after a few months → 404 → ``Runtime.callFunctionOn timed out`` during
// init, and (b) drifts away from whatever wwebjs's internal selectors
// actually expect → ``authenticated`` fires but ``ready`` never does.
//
// Without webVersionCache, wwebjs loads web.whatsapp.com directly, using
// the same JS that the user's actual browser uses. That tracks WhatsApp's
// current build and matches wwebjs's selectors most reliably. If a future
// WhatsApp update breaks wwebjs's selectors, the fix is to bump the
// ``whatsapp-web.js`` package version, not to re-introduce a pinned HTML
// that will go stale a few months later.

function buildClient() {
  return new Client({
    authStrategy: new LocalAuth({ dataPath: AUTH_DIR }),
    puppeteer: {
      headless: true,
      protocolTimeout: 120000,
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-timer-throttling",
      ],
    },
  });
}

// ``client`` always points at the CURRENT generation's wweb.js client so
// the command handlers below (which reference it lazily) act on the live
// instance.
let client = null;

// Track message IDs sent by us so we can skip them in message_create
const ownSentIds = new Set();
let isReady = false;
let catchupDone = false;
let readyTimestamp = 0; // Unix timestamp (seconds) when client became ready
let ownerPhone = "";
let ownerName = "";
let selfChatId = "";
let ownerLid = ""; // owner's @lid identity (WhatsApp's anonymized addressing)
let lastLidAttempt = 0;

function resetSessionState() {
  isReady = false;
  catchupDone = false;
  readyTimestamp = 0;
  selfChatId = "";
  ownerLid = "";
  lastLidAttempt = 0;
  checkedLids.clear();
}

// msg.id._serialized can come back undefined when WhatsApp ships a build
// ahead of whatsapp-web.js (observed live 2026-08-17: a self-chat photo
// arrived with no id, so the agent had no handle for downloadMedia).
// Rebuild it from the id parts — the serialized form IS
// `${fromMe}_${remote}_${id}` — and log loudly when even that fails,
// since an id-less media message cannot be downloaded later.
function msgIdOf(msg) {
  const mid = msg && msg.id;
  if (!mid) return "";
  if (mid._serialized) return mid._serialized;
  const remote =
    mid.remote && mid.remote._serialized ? mid.remote._serialized : mid.remote;
  if (mid.id && remote !== undefined) {
    const rebuilt = [mid.fromMe === true ? "true" : "false", String(remote), String(mid.id)].join("_");
    log(`msg.id._serialized missing — rebuilt as ${rebuilt}`);
    return rebuilt;
  }
  log("msg.id._serialized missing and could not be rebuilt — media download by id will not work for this message");
  return "";
}

// getMessageById needs the exact serialized key WhatsApp uses internally.
// A rebuilt id (msgIdOf fallback) can disagree on the `remote` component —
// observed live 2026-08-17: a @lid self-chat photo rebuilt as
// `true_…@lid_HASH` while the store key used a different remote, so
// getMessageById returned nothing. The hash component is unique, so on a
// miss, find the real key in the in-page message store (same
// window.require pattern as leanUnreadChats) and retry with it.
async function resolveMessage(messageId) {
  let msg = null;
  try {
    msg = await client.getMessageById(messageId);
  } catch (err) {
    log(`getMessageById(${messageId}) threw: ${errStr(err)}`);
  }
  if (msg) return msg;
  // Fallback that never touches id._serialized (broken store-wide on the
  // builds where msgIdOf had to rebuild the id, so getMessageById — and
  // any recovered "real" key — is unusable): fetch recent messages from
  // the chat named inside the id and match on the raw unique hash.
  const parts = String(messageId || "").split("_");
  if (parts.length < 3) return null;
  const hash = parts[parts.length - 1];
  const chatId = parts.slice(1, parts.length - 1).join("_");
  try {
    const chat = await client.getChatById(chatId);
    const recent = await chat.fetchMessages({ limit: 100 });
    for (const m of recent) {
      if (m.id && m.id.id === hash) {
        log(`Resolved message ${hash} via fetchMessages fallback`);
        return m;
      }
    }
    log(`Message hash ${hash} not in the last ${recent.length} messages of ${chatId}`);
  } catch (err) {
    log(`fetchMessages fallback for ${chatId} failed: ${errStr(err)}`);
  }
  return null;
}

// In-page media download that never touches wwebjs's high-level message
// APIs — getMessageById / fetchMessages / getChat are all broken when
// WhatsApp's build outruns wwebjs (observed live 2026-08-17: minified "r"
// errors from each). Same window.require pattern as leanUnreadChats,
// which keeps working through the drift. Mirrors the body of wwebjs
// Message.downloadMedia, but finds the message model by its unique id
// hash instead of the (broken) serialized key.
async function leanDownloadMedia(hash) {
  return await client.pupPage.evaluate(async (h) => {
    const coll = window
      .require("WAWebMsgCollection")
      .MsgCollection.getModelsArray();
    let msg = null;
    for (const m of coll) {
      try {
        if (m.id && m.id.id === h) { msg = m; break; }
      } catch (_) { /* skip malformed models */ }
    }
    if (!msg) return { error: "message not in store (ask the sender to resend, or open the chat)" };
    // Fresh media carries directPath/mediaKey/hashes on the model already —
    // decrypt directly. msg.downloadMedia() (the re-fetch path for expired
    // media) is itself drift-broken on this build ("addAnnotations"
    // TypeError, 2026-08-17), so it is a last resort only.
    if (!msg.directPath || !msg.mediaKey) {
      try {
        await msg.downloadMedia({ downloadEvenIfExpensive: true, rmrReason: 1 });
      } catch (e1) {
        try {
          await msg.downloadMedia();
        } catch (e2) {
          return { error: `media not resolvable: ${(e2 && e2.message) || (e1 && e1.message) || "unknown"}` };
        }
      }
      if (!msg.directPath || !msg.mediaKey) {
        return { error: "message media has no directPath/mediaKey (expired or unsupported type)" };
      }
    }
    const dm = window.require("WAWebDownloadManager").downloadManager;
    // downloadQpl: WhatsApp's newer builds require a QPL (perf logger)
    // object and call addAnnotations/addPoint on it — omitting it is the
    // "reading 'addAnnotations'" TypeError (wwebjs PR #4010's fix).
    const mockQpl = {
      addAnnotations: function () { return this; },
      addPoint: function () { return this; },
    };
    const buf = await dm.downloadAndMaybeDecrypt({
      directPath: msg.directPath,
      encFilehash: msg.encFilehash,
      filehash: msg.filehash,
      mediaKey: msg.mediaKey,
      mediaKeyTimestamp: msg.mediaKeyTimestamp,
      type: msg.type,
      signal: new AbortController().signal,
      downloadQpl: mockQpl,
    });
    const bytes = new Uint8Array(buf);
    let bin = "";
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
    }
    return {
      data_b64: btoa(bin),
      mimetype: msg.mimetype || "",
      filename: msg.filename || "",
    };
  }, hash);
}

// Minified errors from inside WhatsApp Web's bundle carry messages like
// "r" — useless alone. Always log the first stack frames too.
function errStr(err) {
  const stack = String(err && err.stack ? err.stack : "")
    .split("\n")
    .slice(0, 3)
    .join(" | ");
  return `${err && err.message ? err.message : err}${stack ? ` [${stack}]` : ""}`;
}

// getChat()/getContact() reach into WhatsApp Web's minified internals and
// are the FIRST thing to break when WhatsApp ships a build ahead of
// whatsapp-web.js (observed live 2026-08-05: every message failed with
// "Error handling message: r" — zero messages reached CraftBot although the
// core msg object was fine). Enrichment is best-effort: a message with a
// fallback chat/contact beats a dropped message.
async function safeChat(msg) {
  try {
    return await msg.getChat();
  } catch (err) {
    log(`getChat failed (degrading): ${errStr(err)}`);
    return null;
  }
}

async function safeContact(msg) {
  try {
    return await msg.getContact();
  } catch (err) {
    log(`getContact failed (degrading): ${errStr(err)}`);
    return null;
  }
}

function chatFallback(chat, jid) {
  if (chat) {
    return {
      id: chat.id._serialized,
      name: chat.name || chat.id._serialized,
      is_group: chat.isGroup,
      is_muted: chat.isMuted,
    };
  }
  return {
    id: jid || "",
    name: jid || "",
    is_group: String(jid || "").endsWith("@g.us"),
    is_muted: false,
  };
}

function contactFallback(contact, jid) {
  if (contact) {
    return {
      id: contact.id._serialized,
      name: contact.pushname || contact.name || "",
      number: contact.number || "",
      is_group: contact.isGroup,
    };
  }
  return {
    id: jid || "",
    name: "",
    number: String(jid || "").split("@")[0],
    is_group: String(jid || "").endsWith("@g.us"),
  };
}

function jidUser(jid) {
  // "447…:12@c.us" → "447…" (":12" is a per-device suffix, same account)
  return String(jid || "").split("@")[0].split(":")[0];
}

/** Same account, addressing-scheme-blind: compares the user part only. */
function sameUser(a, b) {
  const ua = jidUser(a);
  const ub = jidUser(b);
  return !!ua && !!ub && ua === ub;
}

// Resolve the owner's @lid identity straight from WhatsApp's Store. Under
// the @lid rollout the self chat is addressed as xxx@lid, which matches
// neither the wid (447…@c.us) nor msg.from — so without this, self-chat
// detection has nothing to compare against when getChatById() is broken.
// This is a far smaller internals surface than getChat()/getChatById()
// (observed 2026-08-05: those threw minified "r" on every call while the
// page itself was healthy), so it tends to survive builds that break the
// chat getters. Throttled: at most one attempt per minute.
async function resolveOwnerLid() {
  const now = Date.now();
  if (ownerLid || now - lastLidAttempt < 60_000) return ownerLid;
  lastLidAttempt = now;
  try {
    // wwebjs ≥1.31 does NOT define window.Store — page internals are
    // reached via window.require('WAWeb…') modules, the same way wwebjs's
    // own injected code does (see src/Client.js: WAWebUserPrefsMeUser).
    // Probing window.Store.* here silently returns empty (observed
    // 2026-08-05, two rounds).
    const lid = await client.pupPage.evaluate(() => {
      const ser = (x) => {
        try {
          return (x && (x._serialized || (x.toString ? x.toString() : ""))) || "";
        } catch (e) {
          return "";
        }
      };
      try {
        const me = window.require("WAWebUserPrefsMeUser");
        // Source 1: the lid identity WhatsApp already knows for this session
        const direct = ser(me.getMaybeMeLidUser?.());
        if (direct) return direct;
        // Source 2: map own phone-number wid → current lid
        const pn = me.getMaybeMePnUser?.();
        if (pn) {
          const mapped = ser(
            window.require("WAWebApiContact").getCurrentLid?.(pn)
          );
          if (mapped) return mapped;
        }
      } catch (e) {}
      return "";
    });
    if (lid) {
      ownerLid = String(lid);
      log(`Owner lid resolved: ${ownerLid}`);
    } else {
      log("Owner lid not available (getMaybeMeLidUser + getCurrentLid empty)");
    }
  } catch (err) {
    log(`Owner lid resolution failed: ${errStr(err)}`);
  }
  return ownerLid;
}

// Lids we already tested against the owner's phone number — each lid is
// checked at most once per session so a busy non-self chat can't spam
// page evaluations.
const checkedLids = new Set();

// Decisive per-lid check: does this @lid map back to the owner's phone
// number? Uses WAWebApiContact.getPhoneNumber — the same lid→phone
// mapping wwebjs's own injected helpers use (src/util/Injected/Utils.js).
async function lidMatchesOwner(lidJid) {
  if (!lidJid || !ownerPhone || checkedLids.has(lidJid)) return false;
  checkedLids.add(lidJid);
  try {
    const matches = await client.pupPage.evaluate((lid, phone) => {
      try {
        const wid = window.require("WAWebWidFactory").createWid(lid);
        const pn = window.require("WAWebApiContact").getPhoneNumber?.(wid);
        const s = (pn && (pn._serialized || (pn.toString ? pn.toString() : ""))) || "";
        const user = String(s).split("@")[0].split(":")[0];
        return !!user && user === phone;
      } catch (e) {
        return false;
      }
    }, lidJid, jidUser(ownerPhone));
    if (matches) {
      ownerLid = lidJid;
      log(`Owner lid resolved via contact lookup: ${ownerLid}`);
    } else {
      log(`Lid ${lidJid} does not map to owner phone (not the self chat)`);
    }
    return matches;
  } catch (err) {
    log(`Lid owner check failed for ${lidJid}: ${errStr(err)}`);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Lean in-page reads — survive wwebjs/WhatsApp build drift
// ---------------------------------------------------------------------------

// Lean unread-chat scan that bypasses wwebjs's getChats(). getChats()
// serializes every chat model and is the first thing to break when
// WhatsApp ships a build ahead of whatsapp-web.js; catchup only needs
// ids + unread counters, which we can read straight off the page's chat
// collection (same window.require pattern as resolveOwnerLid — probing
// window.Store.* here silently returns empty on wwebjs ≥1.31).
async function leanUnreadChats() {
  return await client.pupPage.evaluate(() => {
    const out = [];
    const models = window
      .require("WAWebChatCollection")
      .ChatCollection.getModelsArray();
    for (const chat of models) {
      try {
        if (!chat.unreadCount || chat.unreadCount <= 0) continue;
        const id = chat.id && chat.id._serialized;
        if (!id) continue;
        out.push({
          id,
          name: chat.formattedTitle || chat.name || id,
          unread_count: chat.unreadCount,
          is_group: !!(chat.isGroup || (chat.id && chat.id.server === "g.us")),
          is_muted: !!(chat.mute && (chat.mute.isMuted || chat.mute.expiration > 0)),
        });
      } catch (e) { /* skip malformed chat model */ }
    }
    return out;
  });
}

// Full-chat twin of leanUnreadChats for the get_chats/search paths: reads
// the fields the command consumers need straight off the page's chat
// collection, no wwebjs serialization involved.
async function leanChats(limit) {
  return await client.pupPage.evaluate((lim) => {
    const out = [];
    const models = window
      .require("WAWebChatCollection")
      .ChatCollection.getModelsArray();
    for (const chat of models) {
      try {
        const id = chat.id && chat.id._serialized;
        if (!id) continue;
        let lastBody = "";
        let lastTs = 0;
        try {
          const msgs = chat.msgs && chat.msgs.getModelsArray ? chat.msgs.getModelsArray() : [];
          const last = msgs.length ? msgs[msgs.length - 1] : null;
          lastBody = (last && last.body) || "";
          lastTs = (last && last.t) || 0;
        } catch (e) { /* last message is best-effort */ }
        out.push({
          id,
          name: chat.formattedTitle || chat.name || id,
          is_group: !!(chat.isGroup || (chat.id && chat.id.server === "g.us")),
          is_muted: !!(chat.mute && (chat.mute.isMuted || chat.mute.expiration > 0)),
          unread_count: chat.unreadCount || 0,
          last_message: lastBody,
          timestamp: lastTs,
        });
      } catch (e) { /* skip malformed chat model */ }
    }
    // Most-recent first, like wwebjs getChats().
    out.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
    return lim ? out.slice(0, lim) : out;
  }, limit || 0);
}

// getChats() with the lean fallback applied — the shape both consumers
// (get_chats command, search_contact chat scan) need.
async function chatsWithFallback(limit) {
  try {
    const chats = await client.getChats();
    return chats.slice(0, limit || chats.length).map((c) => ({
      id: c.id._serialized,
      name: c.name || c.id._serialized,
      is_group: c.isGroup,
      is_muted: c.isMuted,
      unread_count: c.unreadCount,
      last_message: c.lastMessage?.body || "",
      timestamp: c.lastMessage?.timestamp || 0,
    }));
  } catch (err) {
    log(`getChats failed, using lean fallback: ${errStr(err)}`);
    return await leanChats(limit);
  }
}

// In-page contact filter via window.require (window.Store.Contact is
// silently empty on wwebjs ≥1.31 — same drift class as the chat getters).
async function leanContactSearch(query) {
  return await client.pupPage.evaluate((q) => {
    const needle = (q || "").toLowerCase();
    return window
      .require("WAWebContactCollection")
      .ContactCollection.getModelsArray()
      .filter((c) => {
        try {
          const name = (c.pushname || c.name || c.formattedName || "").toLowerCase();
          const number = (c.id && c.id.user) || "";
          return name.includes(needle) || number.includes(needle);
        } catch (e) {
          return false;
        }
      })
      .slice(0, 20)
      .map((c) => {
        const serialized = c.id._serialized;
        const isLid = serialized.endsWith("@lid");
        return {
          id: serialized,
          name: c.pushname || c.name || c.formattedName || "",
          number: isLid ? serialized : ((c.id && c.id.user) || ""),
          is_group: !!c.isGroup,
        };
      });
  }, query || "");
}

// ---------------------------------------------------------------------------
// ClientGeneration — one client, its handlers, its timers, one dispose
// ---------------------------------------------------------------------------

let currentGen = null;
let attempt = 0; // incremented ONLY in launchGeneration()

class ClientGeneration {
  constructor(id) {
    this.id = id;
    this.disposed = false;
    this.phase = "LAUNCH"; // LAUNCH | QR_WAIT | INJECT | READY
    this.timers = new Set();
    this.launchWatchdog = null;
    this.injectWatchdog = null;
    this.client = buildClient();
    attachHandlers(this);
  }

  /** The single event gate: only the live, current generation may act. */
  get isCurrent() {
    return currentGen === this && !this.disposed;
  }

  setTimer(fn, ms) {
    const t = setTimeout(() => {
      this.timers.delete(t);
      fn();
    }, ms);
    this.timers.add(t);
    return t;
  }

  clearTimer(t) {
    if (t) {
      clearTimeout(t);
      this.timers.delete(t);
    }
  }

  clearAllTimers() {
    for (const t of this.timers) clearTimeout(t);
    this.timers.clear();
    this.launchWatchdog = null;
    this.injectWatchdog = null;
  }

  armLaunchWatchdog() {
    this.launchWatchdog = this.setTimer(() => {
      this.launchWatchdog = null;
      if (!this.isCurrent || this.phase !== "LAUNCH") return;
      log(`Stuck in LAUNCH for ${LAUNCH_TIMEOUT_MS / 1000}s — recovering (attempt ${attempt})`);
      recoverFrom(this, "stuck before qr/authenticated").catch(fatalCrash);
    }, LAUNCH_TIMEOUT_MS);
  }

  armInjectWatchdog() {
    this.injectWatchdog = this.setTimer(() => {
      this.injectWatchdog = null;
      if (!this.isCurrent || this.phase !== "INJECT") return;
      // NO synthetic ready and NO in-process retry: a ready that never
      // fires means wwebjs's injected listeners never attached — exit
      // cleanly and let the Python supervisor restart us with backoff.
      log(`'ready' not received within ${INJECT_TIMEOUT_MS / 1000}s of authenticated — exiting for supervised restart`);
      emitEvent("error", {
        message: "WhatsApp client authenticated but never became ready (message receive would not work)",
        fatal: true,
      });
      this.dispose()
        .catch(() => {})
        .then(() => process.exit(1));
    }, INJECT_TIMEOUT_MS);
  }

  browserPid() {
    try {
      const proc = this.client.pupBrowser && this.client.pupBrowser.process();
      return (proc && proc.pid) || null;
    } catch (e) {
      return null;
    }
  }

  /**
   * Full teardown of THIS generation: timers → handlers → destroy →
   * verify the Chromium tree is actually gone (PID-exact kill on
   * timeout — never name/cmdline matching, which on Windows killed
   * nothing and on multi-account setups risks the wrong browser).
   */
  async dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.clearAllTimers();
    const pid = this.browserPid();
    try {
      this.client.removeAllListeners();
    } catch (e) { /* already dead */ }
    try {
      await this.client.destroy();
    } catch (err) {
      log(`destroy during dispose: ${errStr(err)}`);
    }
    await ensureBrowserGone(pid);
  }
}

/** Wait for a pid to vanish; returns true when gone. */
async function pidGone(pid, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      process.kill(pid, 0); // signal 0 = existence probe
    } catch (e) {
      return true;
    }
    await sleep(200);
  }
  return false;
}

/** After destroy(): verify Chromium exited; force-kill by exact PID if not. */
async function ensureBrowserGone(pid) {
  if (!pid) return;
  if (await pidGone(pid, 5000)) return;
  log(`Chromium pid ${pid} still alive after destroy — force killing`);
  try {
    if (process.platform === "win32") {
      const { execSync } = require("child_process");
      execSync(`taskkill /F /T /PID ${pid}`, { stdio: "ignore" });
    } else {
      process.kill(pid, "SIGKILL");
    }
  } catch (e) { /* raced its own exit */ }
  if (!(await pidGone(pid, 5000))) {
    log(`Chromium pid ${pid} survived force kill — profile may stay locked`);
  }
}

// Chromium teardown takes seconds; relaunching immediately collides with
// the dying browser ("The browser is already running for …/session").
// Between attempts: remove Chromium's Singleton* lock files and back off.
// (Orphan processes are handled by ensureBrowserGone's PID-exact kill in
// dispose — no name/cmdline matching anywhere.)
async function settleBetweenAttempts(attemptNo) {
  const fs = require("fs");
  const sessionDir = path.join(AUTH_DIR, "session");
  await sleep(3000 * Math.max(1, attemptNo));
  for (const name of ["SingletonLock", "SingletonCookie", "SingletonSocket"]) {
    try { fs.rmSync(path.join(sessionDir, name), { force: true }); } catch (_) {}
  }
}

async function recoverFrom(gen, why) {
  if (!gen.isCurrent) return;
  await gen.dispose();
  if (attempt > MAX_LAUNCH_RETRIES) {
    log(`Max launch retries reached — bridge giving up (${why})`);
    emitEvent("error", {
      message: `WhatsApp bridge could not start: ${why}`,
      fatal: true,
    });
    process.exit(1);
  }
  await settleBetweenAttempts(attempt);
  launchGeneration().catch(fatalCrash);
}

async function launchGeneration() {
  attempt += 1; // the ONLY place the counter moves
  resetSessionState();
  const gen = new ClientGeneration(attempt);
  currentGen = gen;
  client = gen.client;
  gen.armLaunchWatchdog();
  log(`Initializing WhatsApp client... (attempt ${attempt}/${MAX_LAUNCH_RETRIES + 1})`);
  try {
    await gen.client.initialize();
  } catch (err) {
    if (!gen.isCurrent) return; // superseded while initializing
    log(`Initialize error: ${errStr(err)}`);
    await recoverFrom(gen, `initialize failed: ${errStr(err)}`);
  }
}

function fatalCrash(err) {
  log(`FATAL: ${errStr(err)}`);
  try {
    emitEvent("error", { message: `WhatsApp bridge crashed: ${errStr(err)}`, fatal: true });
  } catch (_) {}
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Client Events — attached per generation, gated on gen.isCurrent
// ---------------------------------------------------------------------------

function attachHandlers(gen) {
  const c = gen.client;

  c.on("qr", async (qr) => {
    if (!gen.isCurrent) return;
    // QR on screen = a human is (maybe) reaching for their phone. The
    // watchdog is suspended: total-QR-time policy (recycle after N
    // minutes, abandon when nobody is polling) belongs to the Python
    // LinkFlow, never to a destroy-and-retry loop down here (that loop
    // is exactly what used to kill the browser mid-scan).
    gen.phase = "QR_WAIT";
    gen.clearTimer(gen.launchWatchdog);
    gen.launchWatchdog = null;
    log("QR code received");
    try {
      const dataUrl = await qrcode.toDataURL(qr);
      if (!gen.isCurrent) return;
      emitEvent("qr", { qr_string: qr, qr_data_url: dataUrl });
    } catch (err) {
      if (!gen.isCurrent) return;
      emitEvent("qr", { qr_string: qr, qr_data_url: null });
    }
  });

  c.on("authenticated", () => {
    if (!gen.isCurrent) return;
    log("Authenticated");
    gen.phase = "INJECT";
    gen.clearTimer(gen.launchWatchdog);
    gen.launchWatchdog = null;
    gen.armInjectWatchdog();
    emitEvent("authenticated");
  });

  c.on("auth_failure", (msg) => {
    if (!gen.isCurrent) return;
    log(`Auth failure: ${msg}`);
    emitEvent("auth_failure", { message: String(msg) });
  });

  c.on("ready", async () => {
    if (!gen.isCurrent) return;
    gen.phase = "READY";
    gen.clearTimer(gen.injectWatchdog);
    gen.injectWatchdog = null;
    isReady = true;
    readyTimestamp = Math.floor(Date.now() / 1000);
    log("Client ready");

    // Extract owner phone
    try {
      if (c.info && c.info.wid) {
        ownerPhone = c.info.wid.user || "";
        ownerName = c.info.pushname || "";
        log(`Connected as +${ownerPhone} (${ownerName})`);
        // Discover self-chat ID (may be @lid or @c.us)
        try {
          const ownJid = c.info.wid._serialized;
          const selfChat = await c.getChatById(ownJid);
          selfChatId = selfChat?.id?._serialized || ownJid;
          log(`Self-chat ID: ${selfChatId}`);
        } catch (e) {
          selfChatId = c.info.wid._serialized;
          log(`Self-chat fallback to wid: ${selfChatId}`);
        }
        // The wid alone can't match a @lid-addressed self chat, so grab the
        // lid identity too — especially important when getChatById() above
        // just failed and selfChatId is only the wid fallback.
        await resolveOwnerLid();
      }
    } catch (err) {
      log(`Could not extract owner info: ${err.message}`);
    }

    if (!gen.isCurrent) return;
    emitEvent("ready", {
      owner_phone: ownerPhone,
      owner_name: ownerName,
      wid: c.info?.wid?._serialized || "",
    });

    // Catch-up: send current unread chats. Prefer wwebjs getChats() (richer),
    // falling back immediately to the lean in-page scan when getChats() is
    // broken by a WhatsApp build ahead of whatsapp-web.js (observed live
    // 2026-08-12: getChats() consistently failed with minified "r" while the
    // lean scan worked — retrying only delayed catchup, so we don't).
    let unread = null;
    try {
      const chats = await c.getChats();
      unread = chats
        .filter((chat) => chat.unreadCount > 0)
        .map((chat) => ({
          id: chat.id._serialized,
          name: chat.name || chat.id._serialized,
          unread_count: chat.unreadCount,
          is_group: chat.isGroup,
          is_muted: chat.isMuted,
        }));
    } catch (err) {
      log(`Catchup getChats failed, using lean fallback: ${errStr(err)}`);
    }
    if (unread === null) {
      try {
        unread = await leanUnreadChats();
        log("Catchup used lean in-page fallback");
      } catch (err) {
        log(`Catchup lean fallback failed: ${errStr(err)}`);
      }
    }
    if (!gen.isCurrent) return;
    if (unread !== null) {
      emitEvent("catchup", { unread_chats: unread });
      log(`Catchup complete: ${unread.length} unread chat(s)`);
    }
    catchupDone = true; // proceed even if every path failed
  });

  c.on("disconnected", (reason) => {
    if (!gen.isCurrent) return;
    gen.clearTimer(gen.injectWatchdog);
    gen.injectWatchdog = null;
    resetSessionState();
    log(`Disconnected: ${reason}`);
    // Reason "LOGOUT" = the user unlinked this device from their phone;
    // Python maps it to NEEDS_RELINK instead of a reconnect loop.
    emitEvent("disconnected", { reason: String(reason) });
    // A disconnected wweb.js client does not reliably recover in-process.
    // Exit cleanly and let the Python supervisor relaunch with backoff
    // (uniform with crash handling — one restart path, no zombie bridge).
    // Not during shutdown/logout: those paths own their own exit.
    if (!shuttingDown) {
      log("Exiting after disconnect for supervised restart");
      gen.dispose()
        .catch(() => {})
        .then(() => process.exit(0));
    }
  });

  // ── Message events ──────────────────────────────────────────────────────

  c.on("message", async (msg) => {
    if (!gen.isCurrent) return;
    // Skip messages from before the bridge was ready (historical sync)
    if (msg.timestamp && msg.timestamp < readyTimestamp) return;

    try {
      const chat = await safeChat(msg);
      const contact = await safeContact(msg);
      if (!gen.isCurrent) return;

      emitEvent("message", {
        id: msgIdOf(msg),
        from: msg.from,
        to: msg.to,
        body: msg.body || "",
        timestamp: msg.timestamp,
        from_me: msg.fromMe,
        type: msg.type,
        has_media: msg.hasMedia,
        is_forwarded: msg.isForwarded || false,
        mentioned_ids: msg.mentionedIds || [],
        chat: chatFallback(chat, msg.from),
        contact: contactFallback(contact, msg.author || msg.from),
      });
    } catch (err) {
      log(`Error handling message: ${errStr(err)}`);
    }
  });

  c.on("message_create", async (msg) => {
    if (!gen.isCurrent) return;
    // Skip messages from before the bridge was ready (historical sync)
    if (msg.timestamp && msg.timestamp < readyTimestamp) return;
    if (!msg.fromMe) return;

    // Skip messages sent by us via the bridge
    const msgId = msgIdOf(msg);
    if (msgId && ownSentIds.has(msgId)) {
      ownSentIds.delete(msgId);
      return;
    }

    try {
      const chat = await safeChat(msg);
      const chatInfo = chatFallback(chat, msg.to);
      const ownJid = c.info?.wid?._serialized || "";
      // A @lid-addressed self chat matches nothing we know until the owner's
      // lid is resolved — do it now (throttled no-op once resolved) rather
      // than lose the message.
      if (!ownerLid && String(msg.to || "").endsWith("@lid")) {
        await resolveOwnerLid();
      }
      // Self-chat test, layered by addressing scheme. NOTE: `to === from`
      // does NOT hold in the self chat under @lid — `from` stays the wid
      // (447…@c.us) while `to` is the lid (xxx@lid), which is exactly how
      // the 2026-08-05 drop happened. sameUser() compares user parts so a
      // scheme-consistent pair still matches without exact-JID equality.
      let isSelfChat = (msg.from && msg.to === msg.from) ||
        (ownJid && (msg.to === ownJid || sameUser(msg.to, ownJid))) ||
        (ownerLid && (msg.to === ownerLid || sameUser(msg.to, ownerLid))) ||
        (selfChatId && (msg.to === selfChatId || chatInfo.id === selfChatId));

      // Last resort for an unrecognized @lid destination: ask WhatsApp's
      // contact store whether this lid belongs to the owner's own number
      // (once per lid per session). This is what actually catches the self
      // chat when both discovery paths above came up empty at ready.
      if (!isSelfChat && String(msg.to || "").endsWith("@lid")) {
        isSelfChat = await lidMatchesOwner(msg.to);
      }

      if (!gen.isCurrent) return;
      emitEvent("message_sent", {
        id: msgIdOf(msg),
        from: msg.from,
        to: msg.to,
        body: msg.body || "",
        timestamp: msg.timestamp,
        type: msg.type,
        is_self_chat: isSelfChat,
        chat: {
          id: chatInfo.id,
          name: chatInfo.name,
          is_group: chatInfo.is_group,
        },
      });
    } catch (err) {
      log(`Error handling message_create: ${errStr(err)}`);
    }
  });
}

// ---------------------------------------------------------------------------
// Command Handler (stdin)
// ---------------------------------------------------------------------------

async function handleCommand(line) {
  let parsed;
  try {
    parsed = JSON.parse(line);
  } catch {
    log(`Invalid JSON: ${line}`);
    return;
  }

  const { id, cmd, args } = parsed;

  try {
    switch (cmd) {
      case "send_message": {
        if (!isReady) {
          emitResponse(id, { success: false, error: "Client not ready" });
          return;
        }
        let chatId;
        if (args.to.includes("@")) {
          chatId = args.to;
        } else {
          // Resolve number → canonical JID via the server. WhatsApp's
          // LID-based protocol means a locally-constructed `${num}@c.us`
          // can fail with "No LID for user" for contacts the local Store
          // has never seen. getNumberId() primes the LID mapping and
          // also returns null for numbers not on WhatsApp.
          const cleanNum = args.to.replace(/[\s\-\+\(\)]/g, "");
          const wid = await client.getNumberId(cleanNum);
          if (!wid) {
            emitResponse(id, {
              success: false,
              error: `Number ${cleanNum} is not on WhatsApp`,
            });
            return;
          }
          chatId = wid._serialized;
        }
        const sent = await client.sendMessage(chatId, args.text);
        const sentId = msgIdOf(sent);
        if (sentId) ownSentIds.add(sentId);
        emitResponse(id, {
          success: true,
          message_id: sentId || null,
          timestamp: new Date().toISOString(),
        });
        break;
      }

      case "get_status": {
        emitResponse(id, {
          success: true,
          ready: isReady,
          owner_phone: ownerPhone,
          owner_name: ownerName,
          wid: client?.info?.wid?._serialized || "",
        });
        break;
      }

      case "ping": {
        // Heartbeat for the Python session supervisor: answered from the
        // Node side without touching the page, so a hung Chromium still
        // answers — pair with `ready` so the supervisor can tell "page
        // alive" from "process alive".
        emitResponse(id, { success: true, ready: isReady, ts: Date.now() });
        break;
      }

      case "get_chats": {
        if (!isReady) {
          emitResponse(id, { success: false, error: "Client not ready" });
          return;
        }
        const result = await chatsWithFallback(args.limit || 50);
        emitResponse(id, { success: true, chats: result });
        break;
      }

      case "get_chat_messages": {
        if (!isReady) {
          emitResponse(id, { success: false, error: "Client not ready" });
          return;
        }
        const chatId = args.chat_id.includes("@")
          ? args.chat_id
          : `${args.chat_id}@c.us`;
        const chat = await client.getChatById(chatId);
        const messages = await chat.fetchMessages({ limit: args.limit || 50 });
        const result = messages.map((m) => ({
          id: m.id._serialized,
          body: m.body || "",
          from: m.from,
          from_me: m.fromMe,
          timestamp: m.timestamp,
          type: m.type,
          has_media: m.hasMedia,
        }));
        emitResponse(id, { success: true, messages: result });
        break;
      }

      case "search_contact": {
        // Strategy: search chats first (fast, robust, covers the
        // overwhelming case of "find someone I've messaged"). Only if
        // that returns nothing do we fall back to filtering the full
        // address book inside the browser page. We can't use
        // client.getContacts() here — on large accounts the per-contact
        // RPC serialization exceeds Puppeteer's protocolTimeout.
        if (!isReady) {
          emitResponse(id, { success: false, error: "Client not ready" });
          return;
        }
        const query = (args.name || "").toLowerCase();

        const chats = await chatsWithFallback(0);
        let matches = chats
          .filter((ch) => {
            const name = (ch.name || "").toLowerCase();
            const number = String(ch.id || "").split("@")[0];
            return name.includes(query) || number.includes(query);
          })
          .slice(0, 20)
          .map((ch) => {
            // LID-based chats don't have a phone number — surface the
            // full JID instead so the agent round-trips a valid send
            // target through `number`.
            const isLid = String(ch.id || "").endsWith("@lid");
            return {
              id: ch.id,
              name: ch.name || "",
              number: isLid ? ch.id : String(ch.id || "").split("@")[0],
              is_group: ch.is_group,
            };
          });

        if (matches.length === 0) {
          // Fallback: filter the address book in-page (only the matches
          // cross the RPC boundary).
          try {
            matches = await leanContactSearch(args.name || "");
          } catch (err) {
            emitResponse(id, {
              success: false,
              error: `In-page contact filter failed: ${err.message}`,
            });
            return;
          }
        }

        emitResponse(id, { success: true, contacts: matches });
        break;
      }

      case "get_unread_chats": {
        if (!isReady) {
          emitResponse(id, { success: false, error: "Client not ready" });
          return;
        }
        let unreadChats;
        try {
          const allChats = await client.getChats();
          unreadChats = allChats
            .filter((c) => c.unreadCount > 0)
            .map((c) => ({
              id: c.id._serialized,
              name: c.name || c.id._serialized,
              unread_count: c.unreadCount,
              is_group: c.isGroup,
              is_muted: c.isMuted,
            }));
        } catch (err) {
          log(`get_unread_chats getChats failed, using lean fallback: ${errStr(err)}`);
          unreadChats = await leanUnreadChats();
        }
        emitResponse(id, { success: true, unread_chats: unreadChats });
        break;
      }

      case "shutdown": {
        log("Shutdown requested");
        emitResponse(id, { success: true });
        await gracefulShutdown();
        break;
      }

      case "logout": {
        // Full disconnect: logs out of WhatsApp server-side (removes the
        // linked device from the user's phone) AND wipes the LocalAuth
        // data on disk, so the next connect demands a fresh QR.
        log("Logout requested");
        shuttingDown = true; // the LOGOUT 'disconnected' event must not double-exit
        emitResponse(id, { success: true });
        try {
          // client.logout() can hang 30+s on a half-broken connection —
          // give the server-side flush a bounded window, then exit; the
          // Python side force-kills after its own wait anyway.
          if (client) {
            await Promise.race([
              client.logout(),
              sleep(6000).then(() => {
                throw new Error("logout timed out after 6s");
              }),
            ]);
          }
          log("Logged out");
        } catch (err) {
          log(`Logout error: ${err.message}`);
          // Fall through to dispose/exit — even a partial logout is
          // better than leaving the bridge running.
        }
        try {
          if (currentGen) await currentGen.dispose();
        } catch (_) {}
        process.exit(0);
        break;
      }

      // ─────────────────────────────────────────────────────────────────
      // Resolve a number/JID to a canonical chat ID. Helper, not a command.
      // Used by every command that takes a `to` field.
      // ─────────────────────────────────────────────────────────────────

      case "send_media": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        let chatId = args.to;
        if (!chatId.includes("@")) {
          const wid = await client.getNumberId(chatId.replace(/[\s\-\+\(\)]/g, ""));
          if (!wid) { emitResponse(id, { success: false, error: `Number ${chatId} not on WhatsApp` }); return; }
          chatId = wid._serialized;
        }
        let media;
        try {
          media = MessageMedia.fromFilePath(args.file_path);
        } catch (e) {
          emitResponse(id, { success: false, error: `Cannot read file: ${e.message}` });
          return;
        }
        const opts = {};
        if (args.caption) opts.caption = args.caption;
        if (args.send_as_sticker) opts.sendMediaAsSticker = true;
        if (args.send_as_voice) opts.sendAudioAsVoice = true;
        if (args.send_as_document) opts.sendMediaAsDocument = true;
        if (args.quoted_message_id) opts.quotedMessageId = args.quoted_message_id;
        const sent = await client.sendMessage(chatId, media, opts);
        const sentId = msgIdOf(sent);
        if (sentId) ownSentIds.add(sentId);
        emitResponse(id, {
          success: true,
          message_id: sentId || null,
          timestamp: new Date().toISOString(),
        });
        break;
      }

      case "send_location": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        let chatId = args.to;
        if (!chatId.includes("@")) {
          const wid = await client.getNumberId(chatId.replace(/[\s\-\+\(\)]/g, ""));
          if (!wid) { emitResponse(id, { success: false, error: `Number ${chatId} not on WhatsApp` }); return; }
          chatId = wid._serialized;
        }
        const loc = new Location(args.latitude, args.longitude, args.description || "");
        const sent = await client.sendMessage(chatId, loc);
        emitResponse(id, {
          success: true,
          message_id: msgIdOf(sent) || null,
        });
        break;
      }

      case "send_reply": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        let chatId = args.to;
        if (!chatId.includes("@")) {
          const wid = await client.getNumberId(chatId.replace(/[\s\-\+\(\)]/g, ""));
          if (!wid) { emitResponse(id, { success: false, error: `Number ${chatId} not on WhatsApp` }); return; }
          chatId = wid._serialized;
        }
        const sent = await client.sendMessage(chatId, args.text, { quotedMessageId: args.quoted_message_id });
        const sentId = msgIdOf(sent);
        if (sentId) ownSentIds.add(sentId);
        emitResponse(id, { success: true, message_id: sentId || null });
        break;
      }

      case "edit_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await resolveMessage(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        await msg.edit(args.new_body);
        emitResponse(id, { success: true, message_id: args.message_id });
        break;
      }

      case "delete_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await resolveMessage(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        await msg.delete(args.everyone === true);
        emitResponse(id, { success: true, message_id: args.message_id, deleted_for_everyone: args.everyone === true });
        break;
      }

      case "forward_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await resolveMessage(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        let chatId = args.to;
        if (!chatId.includes("@")) {
          const wid = await client.getNumberId(chatId.replace(/[\s\-\+\(\)]/g, ""));
          if (!wid) { emitResponse(id, { success: false, error: `Number ${chatId} not on WhatsApp` }); return; }
          chatId = wid._serialized;
        }
        const chat = await client.getChatById(chatId);
        await msg.forward(chat);
        emitResponse(id, { success: true, forwarded_to: chatId });
        break;
      }

      case "react_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await resolveMessage(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        await msg.react(args.emoji || "");  // empty string removes the reaction
        emitResponse(id, { success: true, message_id: args.message_id, emoji: args.emoji });
        break;
      }

      case "star_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await resolveMessage(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        if (args.starred === false) await msg.unstar(); else await msg.star();
        emitResponse(id, { success: true, message_id: args.message_id, starred: args.starred !== false });
        break;
      }

      case "download_message_media": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        // Preferred path: wwebjs high-level download.
        const msg = await resolveMessage(args.message_id);
        if (msg && msg.hasMedia) {
          try {
            const media = await msg.downloadMedia();
            if (media) {
              emitResponse(id, {
                success: true,
                mimetype: media.mimetype,
                filename: media.filename || "",
                data_b64: media.data,
              });
              break;
            }
          } catch (err) {
            log(`downloadMedia failed, trying lean path: ${errStr(err)}`);
          }
        }
        // Lean in-page path — survives wwebjs build drift.
        const idParts = String(args.message_id || "").split("_");
        const idHash = idParts.length >= 3 ? idParts[idParts.length - 1] : "";
        if (!idHash) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        try {
          const lean = await leanDownloadMedia(idHash);
          if (lean && lean.data_b64) {
            log(`Lean media download succeeded for ${idHash}`);
            emitResponse(id, {
              success: true,
              mimetype: lean.mimetype,
              filename: lean.filename,
              data_b64: lean.data_b64,
            });
          } else {
            const reason = (lean && lean.error) || "unknown";
            log(`Lean media download failed for ${idHash}: ${reason}`);
            emitResponse(id, { success: false, error: `Media download failed: ${reason}` });
          }
        } catch (err) {
          log(`Lean media download threw for ${idHash}: ${errStr(err)}`);
          emitResponse(id, { success: false, error: `Media download failed: ${errStr(err)}` });
        }
        break;
      }

      case "get_quoted_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await resolveMessage(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        const quoted = await msg.getQuotedMessage();
        if (!quoted) { emitResponse(id, { success: true, quoted: null }); return; }
        emitResponse(id, { success: true, quoted: {
          id: quoted.id._serialized, body: quoted.body || "",
          from: quoted.from, from_me: quoted.fromMe, timestamp: quoted.timestamp,
        }});
        break;
      }

      // ─────────────────────────────────────────────────────────────────
      // Chat operations
      // ─────────────────────────────────────────────────────────────────

      case "mark_chat_read": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.chat_id);
        await chat.sendSeen();
        emitResponse(id, { success: true, chat_id: args.chat_id });
        break;
      }

      case "mark_chat_unread": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.chat_id);
        await chat.markUnread();
        emitResponse(id, { success: true, chat_id: args.chat_id });
        break;
      }

      case "archive_chat": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.chat_id);
        if (args.archive === false) await chat.unarchive(); else await chat.archive();
        emitResponse(id, { success: true, chat_id: args.chat_id, archived: args.archive !== false });
        break;
      }

      case "pin_chat": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.chat_id);
        if (args.pin === false) await chat.unpin(); else await chat.pin();
        emitResponse(id, { success: true, chat_id: args.chat_id, pinned: args.pin !== false });
        break;
      }

      case "mute_chat": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.chat_id);
        if (args.mute === false) {
          await chat.unmute();
        } else {
          // unmute_date is unix seconds (optional, otherwise mute forever)
          const date = args.unmute_date ? new Date(args.unmute_date * 1000) : null;
          await chat.mute(date);
        }
        emitResponse(id, { success: true, chat_id: args.chat_id, muted: args.mute !== false });
        break;
      }

      case "clear_chat_messages": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.chat_id);
        await chat.clearMessages();
        emitResponse(id, { success: true, chat_id: args.chat_id });
        break;
      }

      case "delete_chat": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.chat_id);
        await chat.delete();
        emitResponse(id, { success: true, chat_id: args.chat_id });
        break;
      }

      case "send_typing_state": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.chat_id);
        const state = args.state || "typing";  // typing | recording | clear
        if (state === "recording") await chat.sendStateRecording();
        else if (state === "clear") await chat.clearState();
        else await chat.sendStateTyping();
        emitResponse(id, { success: true, chat_id: args.chat_id, state });
        break;
      }

      // ─────────────────────────────────────────────────────────────────
      // Groups
      // ─────────────────────────────────────────────────────────────────

      case "create_group": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        // Resolve participants: phone numbers → JIDs
        const participants = [];
        for (const p of (args.participants || [])) {
          if (p.includes("@")) {
            participants.push(p);
          } else {
            const wid = await client.getNumberId(p.replace(/[\s\-\+\(\)]/g, ""));
            if (wid) participants.push(wid._serialized);
          }
        }
        const result = await client.createGroup(args.name, participants);
        emitResponse(id, {
          success: true,
          group_id: result.gid?._serialized || result.gid || null,
          missing_participants: result.missingParticipants || [],
        });
        break;
      }

      case "group_add_participants": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        const result = await chat.addParticipants(args.participants);
        emitResponse(id, { success: true, result });
        break;
      }

      case "group_remove_participants": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        const result = await chat.removeParticipants(args.participants);
        emitResponse(id, { success: true, result });
        break;
      }

      case "group_promote_participants": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        const result = await chat.promoteParticipants(args.participants);
        emitResponse(id, { success: true, result });
        break;
      }

      case "group_demote_participants": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        const result = await chat.demoteParticipants(args.participants);
        emitResponse(id, { success: true, result });
        break;
      }

      case "group_set_subject": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        await chat.setSubject(args.subject);
        emitResponse(id, { success: true, group_id: args.group_id, subject: args.subject });
        break;
      }

      case "group_set_description": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        await chat.setDescription(args.description);
        emitResponse(id, { success: true, group_id: args.group_id });
        break;
      }

      case "group_get_info": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        emitResponse(id, { success: true, info: {
          id: chat.id._serialized,
          name: chat.name,
          description: chat.description || "",
          owner: chat.owner?._serialized || "",
          created_at: chat.createdAt || null,
          participants: (chat.participants || []).map(p => ({
            id: p.id._serialized,
            is_admin: p.isAdmin,
            is_super_admin: p.isSuperAdmin,
          })),
        }});
        break;
      }

      case "group_leave": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        await chat.leave();
        emitResponse(id, { success: true, group_id: args.group_id });
        break;
      }

      case "group_invite_code": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        const code = await chat.getInviteCode();
        emitResponse(id, { success: true, invite_code: code, invite_url: `https://chat.whatsapp.com/${code}` });
        break;
      }

      case "group_revoke_invite": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const chat = await client.getChatById(args.group_id);
        if (!chat.isGroup) { emitResponse(id, { success: false, error: "Not a group" }); return; }
        const code = await chat.revokeInvite();
        emitResponse(id, { success: true, new_invite_code: code });
        break;
      }

      case "accept_group_invite": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const code = args.invite_code.replace(/^https?:\/\/chat\.whatsapp\.com\//, "");
        const groupId = await client.acceptInvite(code);
        emitResponse(id, { success: true, group_id: groupId });
        break;
      }

      // ─────────────────────────────────────────────────────────────────
      // Contacts
      // ─────────────────────────────────────────────────────────────────

      case "block_contact": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const contact = await client.getContactById(args.contact_id);
        if (args.block === false) await contact.unblock(); else await contact.block();
        emitResponse(id, { success: true, contact_id: args.contact_id, blocked: args.block !== false });
        break;
      }

      case "get_profile_pic_url": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        try {
          const url = await client.getProfilePicUrl(args.contact_id);
          emitResponse(id, { success: true, url: url || "" });
        } catch (e) {
          emitResponse(id, { success: true, url: "" });
        }
        break;
      }

      case "get_contact": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const contact = await client.getContactById(args.contact_id);
        let about = "";
        try { about = await contact.getAbout() || ""; } catch (_) {}
        emitResponse(id, { success: true, contact: {
          id: contact.id._serialized,
          name: contact.name || "",
          pushname: contact.pushname || "",
          short_name: contact.shortName || "",
          number: contact.number || "",
          is_business: contact.isBusiness,
          is_my_contact: contact.isMyContact,
          is_blocked: contact.isBlocked,
          is_user: contact.isUser,
          is_group: contact.isGroup,
          about,
        }});
        break;
      }

      case "get_all_contacts": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        // getContacts() can be slow on large accounts; filter to "my contacts" by default.
        const contacts = await client.getContacts();
        const filtered = args.my_contacts_only === false
          ? contacts
          : contacts.filter(c => c.isMyContact);
        const result = filtered.slice(0, args.limit || 500).map(c => ({
          id: c.id._serialized,
          name: c.name || "",
          pushname: c.pushname || "",
          number: c.number || "",
          is_business: c.isBusiness,
          is_my_contact: c.isMyContact,
        }));
        emitResponse(id, { success: true, contacts: result, count: result.length });
        break;
      }

      case "check_number_on_whatsapp": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const clean = args.number.replace(/[\s\-\+\(\)]/g, "");
        const wid = await client.getNumberId(clean);
        emitResponse(id, {
          success: true,
          on_whatsapp: !!wid,
          jid: wid?._serialized || "",
        });
        break;
      }

      default:
        emitResponse(id, { success: false, error: `Unknown command: ${cmd}` });
    }
  } catch (err) {
    log(`Command error (${cmd}): ${err.message}`);
    emitResponse(id, { success: false, error: err.message });
  }
}

// ---------------------------------------------------------------------------
// Stdin reader
// ---------------------------------------------------------------------------

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  const trimmed = line.trim();
  if (trimmed) handleCommand(trimmed).catch((err) => log(`handleCommand crashed: ${errStr(err)}`));
});

rl.on("close", () => {
  log("stdin closed, shutting down");
  gracefulShutdown().catch(() => process.exit(0));
});

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

let shuttingDown = false;

async function gracefulShutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  log("Shutting down...");
  try {
    if (currentGen) await currentGen.dispose();
  } catch (err) {
    log(`Dispose error during shutdown: ${errStr(err)}`);
  }
  process.exit(0);
}

process.on("SIGINT", () => { gracefulShutdown().catch(() => process.exit(0)); });
process.on("SIGTERM", () => { gracefulShutdown().catch(() => process.exit(0)); });

// A floating rejection or sync throw anywhere means undefined state
// (TargetCloseError/EBUSY used to kill the process silently mid-recovery).
// Exit DELIBERATELY with a fatal event so the Python supervisor sees a
// classified crash and applies backoff, instead of a zombie bridge.
process.on("unhandledRejection", (reason) => {
  if (shuttingDown) return;
  fatalCrash(reason instanceof Error ? reason : new Error(String(reason)));
});
process.on("uncaughtException", (err) => {
  if (shuttingDown) return;
  fatalCrash(err);
});

// Start the first generation. launchGeneration handles its own retries and
// final exit on failure.
launchGeneration().catch(fatalCrash);
