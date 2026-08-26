#!/usr/bin/env node
/**
 * CraftBot WhatsApp Bridge — Baileys edition (protocol-native, no browser).
 *
 * Standalone Node.js process that speaks WhatsApp's WebSocket protocol via
 * Baileys and communicates with the Python agent via stdin/stdout JSON
 * lines. Replaces the whatsapp-web.js + headless-Chromium bridge: sessions
 * are plain key files under <auth_dir>/session (no browser profile to
 * corrupt), reconnects are seconds, and one account costs ~50MB.
 *
 * Protocol (unchanged from the wwebjs bridge — Python is agnostic):
 *   Python → Node (stdin):  { "id": "req_1", "cmd": "...", "args": {...} }
 *   Node → Python (stdout): { "type": "event", "event": "...", "data": {...} }
 *                           { "type": "response", "id": "req_1", "data": {...} }
 *   Logs go to stderr.
 *
 * Events kept identical: qr, authenticated, ready, catchup, disconnected,
 * message, message_sent, auth_failure, error{fatal}.
 *
 * Lifecycle: ONE internal reconnect case — Baileys' post-pairing
 * restartRequired (a normal part of linking). Every other close emits
 * `disconnected` (reason "LOGOUT" when the phone unlinked us — Python
 * parks NEEDS_RELINK) and exits so the Python session actor supervises the
 * restart with backoff, exactly like the old bridge contract.
 */

const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  downloadMediaMessage,
  jidNormalizedUser,
  isJidGroup,
  getContentType,
  Browsers,
} = require("@whiskeysockets/baileys");
const qrcode = require("qrcode");
const path = require("path");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function log(...args) {
  process.stderr.write(`[WA-Bridge] ${args.join(" ")}\n`);
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function emitEvent(event, data = {}) {
  emit({ type: "event", event, data });
}

function emitResponse(id, data = {}) {
  emit({ type: "response", id, data });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function errStr(err) {
  const stack = String(err && err.stack ? err.stack : "")
    .split("\n")
    .slice(0, 3)
    .join(" | ");
  return `${err && err.message ? err.message : err}${stack ? ` [${stack}]` : ""}`;
}

// Baileys wants a pino-like logger; keep it silent — our diagnostics go
// through log() on stderr.
const silentLogger = {
  level: "silent",
  child() { return this; },
  trace() {}, debug() {}, info() {}, warn() {}, error() {}, fatal() {},
};

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const AUTH_DIR = process.argv[2] || path.join(process.cwd(), ".credentials", "whatsapp_wwebjs_auth");
// Key files live in a subdir so the dir root stays free for the Python
// side's marker files (.adopted / .needs_relink).
const SESSION_DIR = path.join(AUTH_DIR, "session");

// First signal (qr or open) must arrive within this budget, else exit for
// supervised restart.
const CONNECT_TIMEOUT_MS = parseInt(process.env.WA_BRIDGE_LAUNCH_TIMEOUT_MS || "", 10) || 90_000;

log(`Auth directory: ${AUTH_DIR}`);

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let sock = null;
let saveCreds = null;
let isReady = false;
let shuttingDown = false;
let sawQr = false;
let catchupEmitted = false;
let readyTimestamp = 0; // unix seconds
let ownerPhone = "";
let ownerName = "";
let ownerJid = ""; // normalized own jid (…@s.whatsapp.net)
let ownerLid = ""; // own @lid identity when known
let connectWatchdog = null;

// Track message IDs sent by us so we can skip them in the fromMe stream
// (the Python client also dedupes by returned message_id — belt+braces).
const ownSentIds = new Set();

// In-memory stores (Baileys keeps no store by itself). Populated from the
// initial history sync + live events; enough for the agent's read surface.
const chats = new Map();    // jid -> {id,name,unread_count,is_group,is_muted,last_message,timestamp}
const contacts = new Map(); // jid -> {id,name,number}
const messages = new Map(); // serializedId -> full Baileys message (FIFO-capped)
const lastMessages = new Map(); // jid -> last message key info (for chatModify)
const MESSAGE_CACHE_MAX = 3000;

function rememberMessage(m) {
  const sid = serializeId(m.key);
  if (!sid) return;
  messages.set(sid, m);
  if (messages.size > MESSAGE_CACHE_MAX) {
    const oldest = messages.keys().next().value;
    messages.delete(oldest);
  }
  if (m.key.remoteJid) {
    lastMessages.set(m.key.remoteJid, {
      key: m.key,
      messageTimestamp: Number(m.messageTimestamp) || Math.floor(Date.now() / 1000),
    });
  }
}

function lastMessagesFor(jid) {
  const entry = lastMessages.get(jid);
  return entry ? [entry] : [];
}

// ---------------------------------------------------------------------------
// JID + message shaping
// ---------------------------------------------------------------------------

function jidUser(jid) {
  return String(jid || "").split("@")[0].split(":")[0];
}

function sameUser(a, b) {
  const ua = jidUser(a);
  const ub = jidUser(b);
  return !!ua && !!ub && ua === ub;
}

/** Accept legacy wwebjs-style jids (…@c.us) and bare numbers. */
function toBaileysJid(value) {
  const v = String(value || "").trim();
  if (v.endsWith("@c.us")) return `${jidUser(v)}@s.whatsapp.net`;
  if (v.includes("@")) return v; // s.whatsapp.net / g.us / lid pass through
  return null; // bare number — caller resolves via onWhatsApp
}

async function resolveTo(to) {
  const direct = toBaileysJid(to);
  if (direct) return direct;
  const clean = String(to || "").replace(/[\s\-\+\(\)]/g, "");
  const results = await sock.onWhatsApp(clean);
  const hit = (results || []).find((r) => r.exists);
  if (!hit) throw new Error(`Number ${clean} is not on WhatsApp`);
  return hit.jid;
}

/** Same serialized shape the old bridge used: `${fromMe}_${remote}_${id}`. */
function serializeId(key) {
  if (!key || !key.id || !key.remoteJid) return "";
  return [key.fromMe ? "true" : "false", key.remoteJid, key.id].join("_");
}

function messageBody(m) {
  const msg = m.message || {};
  return (
    msg.conversation ||
    msg.extendedTextMessage?.text ||
    msg.imageMessage?.caption ||
    msg.videoMessage?.caption ||
    msg.documentMessage?.caption ||
    msg.ephemeralMessage?.message?.conversation ||
    msg.ephemeralMessage?.message?.extendedTextMessage?.text ||
    ""
  );
}

const CONTENT_TYPE_MAP = {
  conversation: "chat",
  extendedTextMessage: "chat",
  imageMessage: "image",
  videoMessage: "video",
  audioMessage: "audio",
  documentMessage: "document",
  documentWithCaptionMessage: "document",
  stickerMessage: "sticker",
  locationMessage: "location",
  liveLocationMessage: "location",
  contactMessage: "vcard",
  contactsArrayMessage: "vcard",
};

function messageType(m) {
  let content = getContentType(m.message || {});
  if (content === "ephemeralMessage") {
    content = getContentType(m.message.ephemeralMessage?.message || {});
  }
  const mapped = CONTENT_TYPE_MAP[content] || content || "unknown";
  if (mapped === "audio" && m.message?.audioMessage?.ptt) return "ptt";
  return mapped;
}

const MEDIA_TYPES = new Set(["image", "video", "audio", "ptt", "document", "sticker"]);

function chatName(jid) {
  const chat = chats.get(jid);
  if (chat && chat.name) return chat.name;
  const contact = contacts.get(jid);
  if (contact && contact.name) return contact.name;
  return jidUser(jid);
}

function chatShape(jid) {
  const chat = chats.get(jid);
  return {
    id: jid,
    name: chatName(jid),
    is_group: isJidGroup(jid) || false,
    is_muted: !!(chat && chat.is_muted),
  };
}

function contactShape(jid) {
  const contact = contacts.get(jid);
  const isLid = String(jid || "").endsWith("@lid");
  return {
    id: jid || "",
    name: (contact && contact.name) || "",
    number: isLid ? jid : jidUser(jid),
    is_group: isJidGroup(jid) || false,
  };
}

function isSelfChat(jid) {
  if (!jid) return false;
  if (ownerJid && sameUser(jid, ownerJid)) return true;
  if (ownerLid && sameUser(jid, ownerLid)) return true;
  return false;
}

function upsertChatFromHistory(c) {
  if (!c || !c.id) return;
  const existing = chats.get(c.id) || {};
  chats.set(c.id, {
    id: c.id,
    name: c.name || existing.name || "",
    unread_count: typeof c.unreadCount === "number" ? c.unreadCount : (existing.unread_count || 0),
    is_group: isJidGroup(c.id) || false,
    is_muted: c.muteEndTime ? Number(c.muteEndTime) * 1000 > Date.now() : (existing.is_muted || false),
    last_message: existing.last_message || "",
    timestamp: Number(c.conversationTimestamp) || existing.timestamp || 0,
  });
}

function touchChatWithMessage(m) {
  const jid = m.key.remoteJid;
  if (!jid || jid === "status@broadcast") return;
  const existing = chats.get(jid) || {
    id: jid,
    name: "",
    unread_count: 0,
    is_group: isJidGroup(jid) || false,
    is_muted: false,
    last_message: "",
    timestamp: 0,
  };
  existing.last_message = messageBody(m) || existing.last_message;
  existing.timestamp = Number(m.messageTimestamp) || Math.floor(Date.now() / 1000);
  if (!m.key.fromMe) existing.unread_count = (existing.unread_count || 0) + 1;
  chats.set(jid, existing);
}

// ---------------------------------------------------------------------------
// Connection lifecycle
// ---------------------------------------------------------------------------

function armConnectWatchdog() {
  clearConnectWatchdog();
  connectWatchdog = setTimeout(() => {
    if (isReady || sawQr || shuttingDown) return;
    log(`No qr/open within ${CONNECT_TIMEOUT_MS / 1000}s — exiting for supervised restart`);
    emitEvent("error", { message: "WhatsApp connection stalled before QR/open", fatal: true });
    process.exit(1);
  }, CONNECT_TIMEOUT_MS);
}

function clearConnectWatchdog() {
  if (connectWatchdog) {
    clearTimeout(connectWatchdog);
    connectWatchdog = null;
  }
}

async function connect() {
  const { state, saveCreds: sc } = await useMultiFileAuthState(SESSION_DIR);
  saveCreds = sc;

  let version;
  try {
    ({ version } = await fetchLatestBaileysVersion());
  } catch (e) {
    log(`fetchLatestBaileysVersion failed (using built-in): ${e.message}`);
  }

  sock = makeWASocket({
    version,
    auth: state,
    logger: silentLogger,
    // A desktop identity keeps history-sync behavior close to the
    // Desktop app's (which is the durability model we want to match).
    browser: Browsers.macOS("Desktop"),
    // Don't steal the phone's notifications by looking permanently online.
    markOnlineOnConnect: false,
    syncFullHistory: false,
    generateHighQualityLinkPreview: false,
  });

  sock.ev.on("creds.update", () => {
    Promise.resolve(saveCreds()).catch((e) => log(`saveCreds failed: ${errStr(e)}`));
  });

  sock.ev.on("connection.update", (update) => {
    handleConnectionUpdate(update).catch((e) => log(`connection.update handler: ${errStr(e)}`));
  });

  sock.ev.on("messaging-history.set", (history) => {
    try {
      for (const c of history.chats || []) upsertChatFromHistory(c);
      for (const ct of history.contacts || []) {
        if (!ct.id) continue;
        contacts.set(ct.id, {
          id: ct.id,
          name: ct.name || ct.notify || ct.verifiedName || "",
          number: jidUser(ct.id),
        });
      }
      for (const m of history.messages || []) {
        if (m && m.key) rememberMessage(m);
      }
      maybeEmitCatchup();
    } catch (e) {
      log(`history sync handling: ${errStr(e)}`);
    }
  });

  sock.ev.on("chats.upsert", (list) => {
    for (const c of list || []) upsertChatFromHistory(c);
  });
  sock.ev.on("chats.update", (list) => {
    for (const c of list || []) {
      if (!c.id) continue;
      const existing = chats.get(c.id);
      if (existing) {
        if (typeof c.unreadCount === "number") existing.unread_count = Math.max(0, c.unreadCount);
        if (c.name) existing.name = c.name;
        if (c.muteEndTime !== undefined) existing.is_muted = Number(c.muteEndTime) * 1000 > Date.now();
        if (c.conversationTimestamp) existing.timestamp = Number(c.conversationTimestamp);
      } else {
        upsertChatFromHistory(c);
      }
    }
  });
  sock.ev.on("contacts.upsert", (list) => {
    for (const ct of list || []) {
      if (!ct.id) continue;
      contacts.set(ct.id, {
        id: ct.id,
        name: ct.name || ct.notify || ct.verifiedName || "",
        number: jidUser(ct.id),
      });
    }
  });

  sock.ev.on("messages.upsert", ({ messages: batch, type }) => {
    if (type !== "notify" && type !== "append") return;
    for (const m of batch || []) {
      try {
        handleIncoming(m, type);
      } catch (e) {
        log(`Error handling message: ${errStr(e)}`);
      }
    }
  });

  armConnectWatchdog();
}

async function handleConnectionUpdate(update) {
  const { connection, lastDisconnect, qr } = update;

  if (qr) {
    sawQr = true;
    clearConnectWatchdog();
    log("QR code received");
    try {
      const dataUrl = await qrcode.toDataURL(qr);
      emitEvent("qr", { qr_string: qr, qr_data_url: dataUrl });
    } catch (e) {
      emitEvent("qr", { qr_string: qr, qr_data_url: null });
    }
  }

  if (connection === "open") {
    clearConnectWatchdog();
    isReady = true;
    readyTimestamp = Math.floor(Date.now() / 1000);
    const user = sock.user || {};
    ownerJid = jidNormalizedUser(user.id || "");
    ownerPhone = jidUser(ownerJid);
    ownerName = user.name || user.verifiedName || "";
    ownerLid = user.lid ? jidNormalizedUser(user.lid) : "";
    log(`Connected as +${ownerPhone} (${ownerName})${ownerLid ? ` lid=${ownerLid}` : ""}`);
    emitEvent("authenticated");
    emitEvent("ready", {
      owner_phone: ownerPhone,
      owner_name: ownerName,
      wid: user.id || "",
    });
    // History sync usually lands within seconds; make sure catchup goes
    // out even if this session gets none.
    setTimeout(() => maybeEmitCatchup(true), 5000);
    return;
  }

  if (connection === "close") {
    isReady = false;
    const code = lastDisconnect?.error?.output?.statusCode;
    if (shuttingDown) return;
    if (code === DisconnectReason.restartRequired) {
      // Normal immediately after pairing — reconnect in-process. This is
      // the pairing handshake completing, so tell Python the scan worked.
      log("Restart required (post-pairing) — reconnecting");
      emitEvent("authenticated");
      connect().catch(fatalCrash);
      return;
    }
    if (code === DisconnectReason.loggedOut) {
      log("Logged out by the phone (unlinked)");
      emitEvent("disconnected", { reason: "LOGOUT" });
      process.exit(0);
    }
    log(`Connection closed (code ${code ?? "unknown"}) — exiting for supervised restart`);
    emitEvent("disconnected", { reason: String(code ?? "closed") });
    process.exit(0);
  }
}

function maybeEmitCatchup(force = false) {
  if (catchupEmitted || !isReady) return;
  const unread = [];
  for (const chat of chats.values()) {
    if ((chat.unread_count || 0) > 0) {
      unread.push({
        id: chat.id,
        name: chat.name || chat.id,
        unread_count: chat.unread_count,
        is_group: chat.is_group,
        is_muted: chat.is_muted,
      });
    }
  }
  if (unread.length === 0 && !force) return;
  catchupEmitted = true;
  emitEvent("catchup", { unread_chats: unread });
  log(`Catchup complete: ${unread.length} unread chat(s)`);
}

function handleIncoming(m, upsertType) {
  if (!m.message || !m.key || !m.key.remoteJid) return;
  const jid = m.key.remoteJid;
  if (jid === "status@broadcast") return;
  rememberMessage(m);
  touchChatWithMessage(m);

  // Skip anything from before this bridge became ready (offline backlog is
  // 'append'; the agent's catchup covers unread state instead).
  const ts = Number(m.messageTimestamp) || 0;
  if (upsertType === "append" || (ts && ts < readyTimestamp)) return;
  if (!isReady) return;

  const sid = serializeId(m.key);
  const body = messageBody(m);
  const mtype = messageType(m);
  const author = m.key.participant || jid;

  if (m.key.fromMe) {
    if (sid && ownSentIds.has(sid)) {
      ownSentIds.delete(sid);
      return;
    }
    emitEvent("message_sent", {
      id: sid,
      from: ownerJid,
      to: jid,
      body,
      timestamp: ts,
      type: mtype,
      is_self_chat: isSelfChat(jid),
      chat: {
        id: jid,
        name: chatName(jid),
        is_group: isJidGroup(jid) || false,
      },
    });
    return;
  }

  emitEvent("message", {
    id: sid,
    from: jid,
    to: ownerJid,
    body,
    timestamp: ts,
    from_me: false,
    type: mtype,
    has_media: MEDIA_TYPES.has(mtype),
    is_forwarded: !!m.message?.extendedTextMessage?.contextInfo?.isForwarded,
    mentioned_ids: m.message?.extendedTextMessage?.contextInfo?.mentionedJid || [],
    chat: chatShape(jid),
    contact: contactShape(author),
  });
}

function fatalCrash(err) {
  log(`FATAL: ${errStr(err)}`);
  try {
    emitEvent("error", { message: `WhatsApp bridge crashed: ${errStr(err)}`, fatal: true });
  } catch (_) {}
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Command helpers
// ---------------------------------------------------------------------------

function requireReady(id) {
  if (!isReady) {
    emitResponse(id, { success: false, error: "Client not ready" });
    return false;
  }
  return true;
}

function storedMessage(messageId) {
  return messages.get(String(messageId || "")) || null;
}

function keyFromSerialized(messageId) {
  const parts = String(messageId || "").split("_");
  if (parts.length < 3) return null;
  return {
    fromMe: parts[0] === "true",
    remoteJid: parts.slice(1, parts.length - 1).join("_"),
    id: parts[parts.length - 1],
  };
}

const EXT_MIME = {
  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
  ".gif": "image/gif", ".webp": "image/webp",
  ".mp4": "video/mp4", ".mov": "video/quicktime", ".3gp": "video/3gpp",
  ".mp3": "audio/mpeg", ".ogg": "audio/ogg; codecs=opus", ".m4a": "audio/mp4",
  ".wav": "audio/wav", ".aac": "audio/aac", ".opus": "audio/ogg; codecs=opus",
  ".pdf": "application/pdf",
};

function guessMime(filePath) {
  return EXT_MIME[path.extname(String(filePath)).toLowerCase()] || "application/octet-stream";
}

function mediaContentFor(args) {
  const filePath = args.file_path;
  const mime = guessMime(filePath);
  const fileName = path.basename(String(filePath));
  if (args.send_as_document) {
    return { document: { url: filePath }, mimetype: mime, fileName };
  }
  if (args.send_as_sticker) {
    return { sticker: { url: filePath } };
  }
  if (args.send_as_voice) {
    return { audio: { url: filePath }, ptt: true, mimetype: "audio/ogg; codecs=opus" };
  }
  if (mime.startsWith("image/")) return { image: { url: filePath } };
  if (mime.startsWith("video/")) return { video: { url: filePath } };
  if (mime.startsWith("audio/")) return { audio: { url: filePath }, mimetype: mime };
  return { document: { url: filePath }, mimetype: mime, fileName };
}

async function groupJidOrRespond(id, groupId) {
  const jid = await resolveTo(groupId);
  if (!isJidGroup(jid)) {
    emitResponse(id, { success: false, error: "Not a group" });
    return null;
  }
  return jid;
}

// ---------------------------------------------------------------------------
// Command handler (stdin)
// ---------------------------------------------------------------------------

async function handleCommand(line) {
  let parsed;
  try {
    parsed = JSON.parse(line);
  } catch {
    log(`Invalid JSON: ${line}`);
    return;
  }
  const { id, cmd, args = {} } = parsed;

  try {
    switch (cmd) {
      case "send_message": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.to);
        const sent = await sock.sendMessage(jid, { text: args.text });
        const sid = serializeId(sent.key);
        if (sid) {
          ownSentIds.add(sid);
          rememberMessage(sent);
        }
        emitResponse(id, {
          success: true,
          message_id: sid || null,
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
          wid: (sock && sock.user && sock.user.id) || "",
        });
        break;
      }

      case "ping": {
        emitResponse(id, { success: true, ready: isReady, ts: Date.now() });
        break;
      }

      case "get_chats": {
        if (!requireReady(id)) return;
        const list = [...chats.values()]
          .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))
          .slice(0, args.limit || 50)
          .map((c) => ({
            id: c.id,
            name: c.name || c.id,
            is_group: c.is_group,
            is_muted: c.is_muted,
            unread_count: c.unread_count || 0,
            last_message: c.last_message || "",
            timestamp: c.timestamp || 0,
          }));
        emitResponse(id, { success: true, chats: list });
        break;
      }

      case "get_chat_messages": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.chat_id);
        const result = [...messages.values()]
          .filter((m) => m.key.remoteJid === jid)
          .sort((a, b) => Number(a.messageTimestamp || 0) - Number(b.messageTimestamp || 0))
          .slice(-(args.limit || 50))
          .map((m) => ({
            id: serializeId(m.key),
            body: messageBody(m),
            from: m.key.fromMe ? ownerJid : (m.key.participant || m.key.remoteJid),
            from_me: !!m.key.fromMe,
            timestamp: Number(m.messageTimestamp) || 0,
            type: messageType(m),
            has_media: MEDIA_TYPES.has(messageType(m)),
          }));
        emitResponse(id, { success: true, messages: result });
        break;
      }

      case "search_contact": {
        if (!requireReady(id)) return;
        const query = (args.name || "").toLowerCase();
        const seen = new Set();
        const matches = [];
        for (const c of chats.values()) {
          const name = (c.name || "").toLowerCase();
          if (name.includes(query) || jidUser(c.id).includes(query)) {
            seen.add(c.id);
            const isLid = c.id.endsWith("@lid");
            matches.push({
              id: c.id,
              name: c.name || "",
              number: isLid ? c.id : jidUser(c.id),
              is_group: c.is_group,
            });
          }
          if (matches.length >= 20) break;
        }
        if (matches.length < 20) {
          for (const ct of contacts.values()) {
            if (seen.has(ct.id)) continue;
            const name = (ct.name || "").toLowerCase();
            if (name.includes(query) || (ct.number || "").includes(query)) {
              const isLid = ct.id.endsWith("@lid");
              matches.push({
                id: ct.id,
                name: ct.name || "",
                number: isLid ? ct.id : ct.number || "",
                is_group: false,
              });
            }
            if (matches.length >= 20) break;
          }
        }
        emitResponse(id, { success: true, contacts: matches });
        break;
      }

      case "get_unread_chats": {
        if (!requireReady(id)) return;
        const unread = [...chats.values()]
          .filter((c) => (c.unread_count || 0) > 0)
          .map((c) => ({
            id: c.id,
            name: c.name || c.id,
            unread_count: c.unread_count,
            is_group: c.is_group,
            is_muted: c.is_muted,
          }));
        emitResponse(id, { success: true, unread_chats: unread });
        break;
      }

      case "shutdown": {
        log("Shutdown requested");
        shuttingDown = true;
        emitResponse(id, { success: true });
        try {
          sock?.end(undefined);
        } catch (_) {}
        process.exit(0);
        break;
      }

      case "logout": {
        // Full disconnect: server-side unlink (removes the entry from the
        // phone's Linked Devices). Python wipes the auth dir afterwards.
        log("Logout requested");
        shuttingDown = true;
        emitResponse(id, { success: true });
        try {
          await Promise.race([
            sock.logout(),
            sleep(6000).then(() => { throw new Error("logout timed out after 6s"); }),
          ]);
          log("Logged out");
        } catch (e) {
          log(`Logout error: ${e.message}`);
        }
        process.exit(0);
        break;
      }

      case "send_media": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.to);
        const content = mediaContentFor(args);
        if (args.caption && !content.audio && !content.sticker) content.caption = args.caption;
        const opts = {};
        if (args.quoted_message_id) {
          const quoted = storedMessage(args.quoted_message_id);
          if (quoted) opts.quoted = quoted;
        }
        const sent = await sock.sendMessage(jid, content, opts);
        const sid = serializeId(sent.key);
        if (sid) {
          ownSentIds.add(sid);
          rememberMessage(sent);
        }
        emitResponse(id, {
          success: true,
          message_id: sid || null,
          timestamp: new Date().toISOString(),
        });
        break;
      }

      case "send_location": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.to);
        const sent = await sock.sendMessage(jid, {
          location: {
            degreesLatitude: args.latitude,
            degreesLongitude: args.longitude,
            name: args.description || "",
          },
        });
        emitResponse(id, { success: true, message_id: serializeId(sent.key) || null });
        break;
      }

      case "send_reply": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.to);
        const quoted = storedMessage(args.quoted_message_id);
        const sent = await sock.sendMessage(
          jid,
          { text: args.text },
          quoted ? { quoted } : {}
        );
        const sid = serializeId(sent.key);
        if (sid) {
          ownSentIds.add(sid);
          rememberMessage(sent);
        }
        emitResponse(id, { success: true, message_id: sid || null });
        break;
      }

      case "edit_message": {
        if (!requireReady(id)) return;
        const key = keyFromSerialized(args.message_id);
        if (!key) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        await sock.sendMessage(key.remoteJid, { text: args.new_body, edit: key });
        emitResponse(id, { success: true, message_id: args.message_id });
        break;
      }

      case "delete_message": {
        if (!requireReady(id)) return;
        const key = keyFromSerialized(args.message_id);
        if (!key) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        if (args.everyone === true) {
          await sock.sendMessage(key.remoteJid, { delete: key });
        } else {
          await sock.chatModify(
            {
              deleteForMe: {
                deleteMedia: false,
                key,
                timestamp: Date.now(),
              },
            },
            key.remoteJid
          );
        }
        emitResponse(id, {
          success: true,
          message_id: args.message_id,
          deleted_for_everyone: args.everyone === true,
        });
        break;
      }

      case "forward_message": {
        if (!requireReady(id)) return;
        const original = storedMessage(args.message_id);
        if (!original) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        const jid = await resolveTo(args.to);
        const sent = await sock.sendMessage(jid, { forward: original });
        const sid = serializeId(sent.key);
        if (sid) ownSentIds.add(sid);
        emitResponse(id, { success: true, forwarded_to: jid });
        break;
      }

      case "react_message": {
        if (!requireReady(id)) return;
        const key = keyFromSerialized(args.message_id);
        if (!key) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        await sock.sendMessage(key.remoteJid, { react: { text: args.emoji || "", key } });
        emitResponse(id, { success: true, message_id: args.message_id, emoji: args.emoji });
        break;
      }

      case "star_message": {
        if (!requireReady(id)) return;
        const key = keyFromSerialized(args.message_id);
        if (!key) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        await sock.chatModify(
          {
            star: {
              messages: [{ id: key.id, fromMe: key.fromMe }],
              star: args.starred !== false,
            },
          },
          key.remoteJid
        );
        emitResponse(id, {
          success: true,
          message_id: args.message_id,
          starred: args.starred !== false,
        });
        break;
      }

      case "download_message_media": {
        if (!requireReady(id)) return;
        const original = storedMessage(args.message_id);
        if (!original) {
          emitResponse(id, {
            success: false,
            error: "Message not found (not in this session's cache — ask the sender to resend)",
          });
          return;
        }
        const buffer = await downloadMediaMessage(
          original,
          "buffer",
          {},
          { logger: silentLogger, reuploadRequest: sock.updateMediaMessage }
        );
        let content = getContentType(original.message || {});
        if (content === "ephemeralMessage") {
          content = getContentType(original.message.ephemeralMessage?.message || {});
        }
        const inner =
          (original.message && (original.message[content] ||
            original.message.ephemeralMessage?.message?.[content])) || {};
        emitResponse(id, {
          success: true,
          mimetype: inner.mimetype || "",
          filename: inner.fileName || "",
          data_b64: Buffer.from(buffer).toString("base64"),
        });
        break;
      }

      case "get_quoted_message": {
        if (!requireReady(id)) return;
        const original = storedMessage(args.message_id);
        const ctx =
          original?.message?.extendedTextMessage?.contextInfo ||
          original?.message?.imageMessage?.contextInfo ||
          original?.message?.videoMessage?.contextInfo ||
          original?.message?.documentMessage?.contextInfo ||
          null;
        if (!ctx || !ctx.quotedMessage) {
          emitResponse(id, { success: true, quoted: null });
          return;
        }
        const qBody =
          ctx.quotedMessage.conversation ||
          ctx.quotedMessage.extendedTextMessage?.text ||
          ctx.quotedMessage.imageMessage?.caption || "";
        const participant = ctx.participant || "";
        emitResponse(id, {
          success: true,
          quoted: {
            id: [sameUser(participant, ownerJid) ? "true" : "false", original.key.remoteJid, ctx.stanzaId].join("_"),
            body: qBody,
            from: participant,
            from_me: sameUser(participant, ownerJid),
            timestamp: 0,
          },
        });
        break;
      }

      // ── Chat operations ────────────────────────────────────────────────

      case "mark_chat_read": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.chat_id);
        await sock.chatModify({ markRead: true, lastMessages: lastMessagesFor(jid) }, jid);
        const chat = chats.get(jid);
        if (chat) chat.unread_count = 0;
        emitResponse(id, { success: true, chat_id: args.chat_id });
        break;
      }

      case "mark_chat_unread": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.chat_id);
        await sock.chatModify({ markRead: false, lastMessages: lastMessagesFor(jid) }, jid);
        emitResponse(id, { success: true, chat_id: args.chat_id });
        break;
      }

      case "archive_chat": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.chat_id);
        await sock.chatModify(
          { archive: args.archive !== false, lastMessages: lastMessagesFor(jid) },
          jid
        );
        emitResponse(id, { success: true, chat_id: args.chat_id, archived: args.archive !== false });
        break;
      }

      case "pin_chat": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.chat_id);
        await sock.chatModify({ pin: args.pin !== false }, jid);
        emitResponse(id, { success: true, chat_id: args.chat_id, pinned: args.pin !== false });
        break;
      }

      case "mute_chat": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.chat_id);
        let mute = null;
        if (args.mute !== false) {
          mute = args.unmute_date
            ? Math.max(0, args.unmute_date * 1000 - Date.now())
            : 365 * 24 * 60 * 60 * 1000; // "forever" ≈ 1 year
        }
        await sock.chatModify({ mute }, jid);
        const chat = chats.get(jid);
        if (chat) chat.is_muted = args.mute !== false;
        emitResponse(id, { success: true, chat_id: args.chat_id, muted: args.mute !== false });
        break;
      }

      case "clear_chat_messages": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.chat_id);
        await sock.chatModify({ clear: true, lastMessages: lastMessagesFor(jid) }, jid);
        emitResponse(id, { success: true, chat_id: args.chat_id });
        break;
      }

      case "delete_chat": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.chat_id);
        await sock.chatModify({ delete: true, lastMessages: lastMessagesFor(jid) }, jid);
        chats.delete(jid);
        emitResponse(id, { success: true, chat_id: args.chat_id });
        break;
      }

      case "send_typing_state": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.chat_id);
        const state = args.state || "typing";
        const presence =
          state === "recording" ? "recording" : state === "clear" ? "paused" : "composing";
        await sock.sendPresenceUpdate(presence, jid);
        emitResponse(id, { success: true, chat_id: args.chat_id, state });
        break;
      }

      // ── Groups ─────────────────────────────────────────────────────────

      case "create_group": {
        if (!requireReady(id)) return;
        const participants = [];
        for (const p of args.participants || []) {
          try {
            participants.push(await resolveTo(p));
          } catch (e) {
            log(`create_group: skipping ${p}: ${e.message}`);
          }
        }
        const result = await sock.groupCreate(args.name, participants);
        emitResponse(id, {
          success: true,
          group_id: result.id || null,
          missing_participants: [],
        });
        break;
      }

      case "group_add_participants":
      case "group_remove_participants":
      case "group_promote_participants":
      case "group_demote_participants": {
        if (!requireReady(id)) return;
        const jid = await groupJidOrRespond(id, args.group_id);
        if (!jid) return;
        const action = {
          group_add_participants: "add",
          group_remove_participants: "remove",
          group_promote_participants: "promote",
          group_demote_participants: "demote",
        }[cmd];
        const jids = [];
        for (const p of args.participants || []) jids.push(await resolveTo(p));
        const result = await sock.groupParticipantsUpdate(jid, jids, action);
        emitResponse(id, { success: true, result });
        break;
      }

      case "group_set_subject": {
        if (!requireReady(id)) return;
        const jid = await groupJidOrRespond(id, args.group_id);
        if (!jid) return;
        await sock.groupUpdateSubject(jid, args.subject);
        emitResponse(id, { success: true, group_id: args.group_id, subject: args.subject });
        break;
      }

      case "group_set_description": {
        if (!requireReady(id)) return;
        const jid = await groupJidOrRespond(id, args.group_id);
        if (!jid) return;
        await sock.groupUpdateDescription(jid, args.description);
        emitResponse(id, { success: true, group_id: args.group_id });
        break;
      }

      case "group_get_info": {
        if (!requireReady(id)) return;
        const jid = await groupJidOrRespond(id, args.group_id);
        if (!jid) return;
        const meta = await sock.groupMetadata(jid);
        emitResponse(id, {
          success: true,
          info: {
            id: meta.id,
            name: meta.subject,
            description: meta.desc || "",
            owner: meta.owner || "",
            created_at: meta.creation || null,
            participants: (meta.participants || []).map((p) => ({
              id: p.id,
              is_admin: p.admin === "admin" || p.admin === "superadmin",
              is_super_admin: p.admin === "superadmin",
            })),
          },
        });
        break;
      }

      case "group_leave": {
        if (!requireReady(id)) return;
        const jid = await groupJidOrRespond(id, args.group_id);
        if (!jid) return;
        await sock.groupLeave(jid);
        emitResponse(id, { success: true, group_id: args.group_id });
        break;
      }

      case "group_invite_code": {
        if (!requireReady(id)) return;
        const jid = await groupJidOrRespond(id, args.group_id);
        if (!jid) return;
        const code = await sock.groupInviteCode(jid);
        emitResponse(id, {
          success: true,
          invite_code: code,
          invite_url: `https://chat.whatsapp.com/${code}`,
        });
        break;
      }

      case "group_revoke_invite": {
        if (!requireReady(id)) return;
        const jid = await groupJidOrRespond(id, args.group_id);
        if (!jid) return;
        const code = await sock.groupRevokeInvite(jid);
        emitResponse(id, { success: true, new_invite_code: code });
        break;
      }

      case "accept_group_invite": {
        if (!requireReady(id)) return;
        const code = String(args.invite_code || "").replace(/^https?:\/\/chat\.whatsapp\.com\//, "");
        const groupId = await sock.groupAcceptInvite(code);
        emitResponse(id, { success: true, group_id: groupId });
        break;
      }

      // ── Contacts ───────────────────────────────────────────────────────

      case "block_contact": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.contact_id);
        await sock.updateBlockStatus(jid, args.block === false ? "unblock" : "block");
        emitResponse(id, {
          success: true,
          contact_id: args.contact_id,
          blocked: args.block !== false,
        });
        break;
      }

      case "get_profile_pic_url": {
        if (!requireReady(id)) return;
        try {
          const jid = await resolveTo(args.contact_id);
          const url = await sock.profilePictureUrl(jid, "image");
          emitResponse(id, { success: true, url: url || "" });
        } catch (e) {
          emitResponse(id, { success: true, url: "" });
        }
        break;
      }

      case "get_contact": {
        if (!requireReady(id)) return;
        const jid = await resolveTo(args.contact_id);
        const contact = contacts.get(jid) || {};
        emitResponse(id, {
          success: true,
          contact: {
            id: jid,
            name: contact.name || "",
            pushname: contact.name || "",
            short_name: "",
            number: jidUser(jid),
            is_business: false,
            is_my_contact: contacts.has(jid),
            is_blocked: false,
            is_user: !isJidGroup(jid),
            is_group: isJidGroup(jid) || false,
            about: "",
          },
        });
        break;
      }

      case "get_all_contacts": {
        if (!requireReady(id)) return;
        let list = [...contacts.values()];
        if (args.my_contacts_only !== false) {
          list = list.filter((c) => !!c.name);
        }
        const result = list.slice(0, args.limit || 500).map((c) => ({
          id: c.id,
          name: c.name || "",
          pushname: c.name || "",
          number: c.number || jidUser(c.id),
          is_business: false,
          is_my_contact: true,
        }));
        emitResponse(id, { success: true, contacts: result, count: result.length });
        break;
      }

      case "check_number_on_whatsapp": {
        if (!requireReady(id)) return;
        const clean = String(args.number || "").replace(/[\s\-\+\(\)]/g, "");
        const results = await sock.onWhatsApp(clean);
        const hit = (results || []).find((r) => r.exists);
        emitResponse(id, {
          success: true,
          on_whatsapp: !!hit,
          jid: (hit && hit.jid) || "",
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
// Stdin reader + lifecycle
// ---------------------------------------------------------------------------

const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  const trimmed = line.trim();
  if (trimmed) handleCommand(trimmed).catch((err) => log(`handleCommand crashed: ${errStr(err)}`));
});
rl.on("close", () => {
  if (shuttingDown) return;
  log("stdin closed, shutting down");
  shuttingDown = true;
  try {
    sock?.end(undefined);
  } catch (_) {}
  process.exit(0);
});

process.on("SIGINT", () => { shuttingDown = true; try { sock?.end(undefined); } catch (_) {} process.exit(0); });
process.on("SIGTERM", () => { shuttingDown = true; try { sock?.end(undefined); } catch (_) {} process.exit(0); });

// A floating rejection means undefined state — exit deliberately with a
// fatal event so the Python supervisor sees a classified crash.
process.on("unhandledRejection", (reason) => {
  if (shuttingDown) return;
  fatalCrash(reason instanceof Error ? reason : new Error(String(reason)));
});
process.on("uncaughtException", (err) => {
  if (shuttingDown) return;
  fatalCrash(err);
});

connect().catch(fatalCrash);
