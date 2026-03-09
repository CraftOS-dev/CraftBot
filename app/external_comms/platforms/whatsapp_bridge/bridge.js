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
 */

const { Client, LocalAuth } = require("whatsapp-web.js");
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

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const AUTH_DIR = process.argv[2] || path.join(process.cwd(), ".credentials", "whatsapp_wwebjs_auth");

log(`Auth directory: ${AUTH_DIR}`);

// ---------------------------------------------------------------------------
// WhatsApp Client
// ---------------------------------------------------------------------------

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: AUTH_DIR }),
  puppeteer: {
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
    ],
  },
});

// Track message IDs sent by us so we can skip them in message_create
const ownSentIds = new Set();
let isReady = false;
let catchupDone = false;
let readyTimestamp = 0; // Unix timestamp (seconds) when client became ready
let ownerPhone = "";
let ownerName = "";

// ---------------------------------------------------------------------------
// Client Events
// ---------------------------------------------------------------------------

client.on("qr", async (qr) => {
  log("QR code received");
  try {
    const dataUrl = await qrcode.toDataURL(qr);
    emitEvent("qr", { qr_string: qr, qr_data_url: dataUrl });
  } catch (err) {
    emitEvent("qr", { qr_string: qr, qr_data_url: null });
  }
});

client.on("authenticated", () => {
  log("Authenticated");
  emitEvent("authenticated");
});

client.on("auth_failure", (msg) => {
  log(`Auth failure: ${msg}`);
  emitEvent("auth_failure", { message: String(msg) });
});

client.on("ready", async () => {
  isReady = true;
  readyTimestamp = Math.floor(Date.now() / 1000);
  log("Client ready");

  // Extract owner phone
  try {
    if (client.info && client.info.wid) {
      ownerPhone = client.info.wid.user || "";
      ownerName = client.info.pushname || "";
      log(`Connected as +${ownerPhone} (${ownerName})`);
    }
  } catch (err) {
    log(`Could not extract owner info: ${err.message}`);
  }

  emitEvent("ready", {
    owner_phone: ownerPhone,
    owner_name: ownerName,
    wid: client.info?.wid?._serialized || "",
  });

  // Catch-up: send current unread chats
  try {
    const chats = await client.getChats();
    const unread = [];
    for (const chat of chats) {
      if (chat.unreadCount > 0) {
        unread.push({
          id: chat.id._serialized,
          name: chat.name || chat.id._serialized,
          unread_count: chat.unreadCount,
          is_group: chat.isGroup,
          is_muted: chat.isMuted,
        });
      }
    }
    emitEvent("catchup", { unread_chats: unread });
    catchupDone = true;
    log(`Catchup complete: ${unread.length} unread chat(s)`);
  } catch (err) {
    log(`Catchup error: ${err.message}`);
    catchupDone = true; // proceed anyway
  }
});

client.on("disconnected", (reason) => {
  isReady = false;
  catchupDone = false;
  readyTimestamp = 0;
  log(`Disconnected: ${reason}`);
  emitEvent("disconnected", { reason: String(reason) });
});

// ---------------------------------------------------------------------------
// Message Events
// ---------------------------------------------------------------------------

client.on("message", async (msg) => {
  // Skip messages from before the bridge was ready (historical sync)
  if (msg.timestamp && msg.timestamp < readyTimestamp) return;

  try {
    const chat = await msg.getChat();
    const contact = await msg.getContact();

    emitEvent("message", {
      id: msg.id._serialized,
      from: msg.from,
      to: msg.to,
      body: msg.body || "",
      timestamp: msg.timestamp,
      from_me: msg.fromMe,
      type: msg.type,
      has_media: msg.hasMedia,
      is_forwarded: msg.isForwarded || false,
      mentioned_ids: msg.mentionedIds || [],
      chat: {
        id: chat.id._serialized,
        name: chat.name || chat.id._serialized,
        is_group: chat.isGroup,
        is_muted: chat.isMuted,
      },
      contact: {
        id: contact.id._serialized,
        name: contact.pushname || contact.name || "",
        number: contact.number || "",
        is_group: contact.isGroup,
      },
    });
  } catch (err) {
    log(`Error handling message: ${err.message}`);
  }
});

client.on("message_create", async (msg) => {
  // Skip messages from before the bridge was ready (historical sync)
  if (msg.timestamp && msg.timestamp < readyTimestamp) return;
  if (!msg.fromMe) return;

  // Skip messages sent by us via the bridge
  const msgId = msg.id?._serialized;
  if (msgId && ownSentIds.has(msgId)) {
    ownSentIds.delete(msgId);
    return;
  }

  try {
    const chat = await msg.getChat();
    const ownJid = client.info?.wid?._serialized || "";
    const isSelfChat = ownJid && msg.to === ownJid;

    emitEvent("message_sent", {
      id: msg.id._serialized,
      from: msg.from,
      to: msg.to,
      body: msg.body || "",
      timestamp: msg.timestamp,
      type: msg.type,
      is_self_chat: isSelfChat,
      chat: {
        id: chat.id._serialized,
        name: chat.name || chat.id._serialized,
        is_group: chat.isGroup,
      },
    });
  } catch (err) {
    log(`Error handling message_create: ${err.message}`);
  }
});

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
        const chatId = args.to.includes("@") ? args.to : `${args.to}@c.us`;
        const sent = await client.sendMessage(chatId, args.text);
        if (sent?.id?._serialized) ownSentIds.add(sent.id._serialized);
        emitResponse(id, {
          success: true,
          message_id: sent?.id?._serialized || null,
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
          wid: client.info?.wid?._serialized || "",
        });
        break;
      }

      case "get_chats": {
        if (!isReady) {
          emitResponse(id, { success: false, error: "Client not ready" });
          return;
        }
        const chats = await client.getChats();
        const result = chats.slice(0, args.limit || 50).map((c) => ({
          id: c.id._serialized,
          name: c.name || c.id._serialized,
          is_group: c.isGroup,
          is_muted: c.isMuted,
          unread_count: c.unreadCount,
          last_message: c.lastMessage?.body || "",
          timestamp: c.lastMessage?.timestamp || 0,
        }));
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
        if (!isReady) {
          emitResponse(id, { success: false, error: "Client not ready" });
          return;
        }
        const contacts = await client.getContacts();
        const query = (args.name || "").toLowerCase();
        const matches = contacts
          .filter((c) => {
            const name = (c.pushname || c.name || "").toLowerCase();
            const number = c.number || "";
            return name.includes(query) || number.includes(query);
          })
          .slice(0, 20)
          .map((c) => ({
            id: c.id._serialized,
            name: c.pushname || c.name || "",
            number: c.number || "",
            is_group: c.isGroup,
          }));
        emitResponse(id, { success: true, contacts: matches });
        break;
      }

      case "get_unread_chats": {
        if (!isReady) {
          emitResponse(id, { success: false, error: "Client not ready" });
          return;
        }
        const allChats = await client.getChats();
        const unreadChats = allChats
          .filter((c) => c.unreadCount > 0)
          .map((c) => ({
            id: c.id._serialized,
            name: c.name || c.id._serialized,
            unread_count: c.unreadCount,
            is_group: c.isGroup,
            is_muted: c.isMuted,
          }));
        emitResponse(id, { success: true, unread_chats: unreadChats });
        break;
      }

      case "shutdown": {
        log("Shutdown requested");
        emitResponse(id, { success: true });
        await gracefulShutdown();
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
  if (trimmed) handleCommand(trimmed);
});

rl.on("close", () => {
  log("stdin closed, shutting down");
  gracefulShutdown();
});

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

async function gracefulShutdown() {
  log("Shutting down...");
  try {
    if (client) await client.destroy();
  } catch (err) {
    log(`Destroy error: ${err.message}`);
  }
  process.exit(0);
}

process.on("SIGINT", gracefulShutdown);
process.on("SIGTERM", gracefulShutdown);

// Start
log("Initializing WhatsApp client...");
client.initialize().catch((err) => {
  log(`Initialize error: ${err.message}`);
  emitEvent("error", { message: err.message });
});
