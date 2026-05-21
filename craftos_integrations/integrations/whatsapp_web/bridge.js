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

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const AUTH_DIR = process.argv[2] || path.join(process.cwd(), ".credentials", "whatsapp_wwebjs_auth");

log(`Auth directory: ${AUTH_DIR}`);

// ---------------------------------------------------------------------------
// WhatsApp Client
// ---------------------------------------------------------------------------

// We deliberately do NOT pin a webVersionCache. Pinning ties us to a
// snapshot from wppconnect-team/wa-version, which (a) prunes old entries
// after a few months → 404 → ``Runtime.callFunctionOn timed out`` during
// init, and (b) drifts away from whatever wwebjs's internal selectors
// actually expect → ``authenticated`` fires but ``ready`` never does, so
// the synthetic-ready fallback kicks in but messages don't actually flow
// because wwebjs's internal listeners haven't attached.
//
// Without webVersionCache, wwebjs loads web.whatsapp.com directly, using
// the same JS that the user's actual browser uses. That tracks WhatsApp's
// current build and matches wwebjs's selectors most reliably. If a future
// WhatsApp update breaks wwebjs's selectors, the fix is to bump the
// ``whatsapp-web.js`` package version, not to re-introduce a pinned HTML
// that will go stale a few months later.

// ``client`` is module-level + ``let`` (not ``const``) so the watchdog/retry
// path can replace it with a fresh instance after a stuck-init recovery.
// Command handlers below reference ``client`` lazily — they always pick up
// the current binding.
let client;

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

// Track message IDs sent by us so we can skip them in message_create
const ownSentIds = new Set();
let isReady = false;
let catchupDone = false;
let readyTimestamp = 0; // Unix timestamp (seconds) when client became ready
let ownerPhone = "";
let ownerName = "";
let selfChatId = "";

// ---------------------------------------------------------------------------
// Client Events
// ---------------------------------------------------------------------------

// Attach all wwebjs event handlers to ``c``. Called once per buildClient() —
// the watchdog/retry path re-runs this against the freshly built client so
// every retry has the same wiring.
function attachHandlers(c) {

c.on("qr", async (qr) => {
  log("QR code received");
  try {
    const dataUrl = await qrcode.toDataURL(qr);
    emitEvent("qr", { qr_string: qr, qr_data_url: dataUrl });
  } catch (err) {
    emitEvent("qr", { qr_string: qr, qr_data_url: null });
  }
});

c.on("authenticated", () => {
  log("Authenticated");
  authedThisAttempt = true;
  if (initWatchdog) { clearTimeout(initWatchdog); initWatchdog = null; }
  emitEvent("authenticated");

  // Ready-watchdog: when wwebjs's selectors drift from what WhatsApp's
  // current bundle exposes, ``authenticated`` fires but ``ready`` never
  // does — and crucially wwebjs's internal message listeners don't attach,
  // so messages don't flow. We wait 60s for the real ``ready``; if it
  // doesn't arrive, we treat it as a stuck-init failure and reuse the
  // existing watchdog/retry path (destroy → rebuild → reinitialize).
  // Only after the retry budget is exhausted do we fall through to a
  // synthetic ``ready`` so sends still work — receive will be broken in
  // that fallback state, but the bridge is at least usable for outbound.
  setTimeout(async () => {
    if (isReady) return;
    if (initAttempt <= MAX_INIT_RETRIES) {
      log(`'ready' not received within 60s of authenticated — treating as stuck init, retrying (attempt ${initAttempt}/${MAX_INIT_RETRIES + 1})`);
      initAttempt += 1;
      try { await client.destroy(); } catch (err) { log(`destroy during ready-retry: ${err.message}`); }
      client = buildClient();
      attachHandlers(client);
      authedThisAttempt = false;
      startClientWithWatchdog();
      return;
    }
    // Retry budget exhausted — fall through to synthetic so sends still work.
    log("'ready' not received and retries exhausted — synthesizing (sends only, receive will not work)");
    try {
      if (client.info && client.info.wid) {
        ownerPhone = client.info.wid.user || ownerPhone;
        ownerName = client.info.pushname || ownerName;
      }
    } catch (_) { /* best-effort */ }
    isReady = true;
    readyTimestamp = Math.floor(Date.now() / 1000);
    emitEvent("ready", {
      owner_phone: ownerPhone,
      owner_name: ownerName,
      wid: client.info?.wid?._serialized || "",
      synthetic: true,
    });
    emitEvent("error", { message: "ready event never fired — message receive will not work. Try restarting the agent or updating whatsapp-web.js.", fatal: false });
  }, 60_000);
});

c.on("auth_failure", (msg) => {
  log(`Auth failure: ${msg}`);
  emitEvent("auth_failure", { message: String(msg) });
});

c.on("ready", async () => {
  isReady = true;
  readyTimestamp = Math.floor(Date.now() / 1000);
  log("Client ready");

  // Extract owner phone
  try {
    if (client.info && client.info.wid) {
      ownerPhone = client.info.wid.user || "";
      ownerName = client.info.pushname || "";
      log(`Connected as +${ownerPhone} (${ownerName})`);
      // Discover self-chat ID (may be @lid or @c.us)
      try {
        const ownJid = client.info.wid._serialized;
        const selfChat = await client.getChatById(ownJid);
        selfChatId = selfChat?.id?._serialized || ownJid;
        log(`Self-chat ID: ${selfChatId}`);
      } catch (e) {
        selfChatId = client.info.wid._serialized;
        log(`Self-chat fallback to wid: ${selfChatId}`);
      }
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

c.on("disconnected", (reason) => {
  isReady = false;
  catchupDone = false;
  readyTimestamp = 0;
  log(`Disconnected: ${reason}`);
  emitEvent("disconnected", { reason: String(reason) });
});

// ---------------------------------------------------------------------------
// Message Events
// ---------------------------------------------------------------------------

c.on("message", async (msg) => {
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

c.on("message_create", async (msg) => {
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
    const isSelfChat = (ownJid && msg.to === ownJid) || (selfChatId && (msg.to === selfChatId || chat.id._serialized === selfChatId));

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

}  // end attachHandlers(c)

// ---------------------------------------------------------------------------
// Init watchdog + retry — auto-recovers from "stuck before authenticated"
//
// Failure mode this protects against: wwebjs's ``client.initialize()`` hangs
// for 2+ minutes during the WhatsApp Web page load (most often when the
// pinned ``webVersionCache`` URL 404s, when leftover Chromium zombies hold
// the auth dir lock, or when WhatsApp pushes a protocol change). The
// "Initialize error: Runtime.callFunctionOn timed out" we see in logs is
// puppeteer's protocolTimeout firing on a wwebjs JS call that never returns.
//
// Strategy: set a 60s watchdog when initialize() is called. If we don't
// reach the ``authenticated`` event within that window, kill Chromium with
// ``client.destroy()``, build a fresh client, re-attach handlers, and
// re-run initialize. After ``MAX_INIT_RETRIES`` failures we emit a fatal
// error and exit non-zero so the Python parent can decide what to do (in
// practice it logs and continues without WhatsApp).
// ---------------------------------------------------------------------------

const MAX_INIT_RETRIES = 2;
const INIT_WATCHDOG_MS = 60_000;
let initAttempt = 0;
let authedThisAttempt = false;
let initWatchdog = null;

async function startClientWithWatchdog() {
  initAttempt += 1;
  authedThisAttempt = false;

  // Cancel any prior watchdog before arming a new one (defensive — should
  // already be cleared by the time we get here).
  if (initWatchdog) clearTimeout(initWatchdog);

  initWatchdog = setTimeout(async () => {
    if (authedThisAttempt) return;  // raced with the auth event
    log(`Stuck before 'authenticated' for ${INIT_WATCHDOG_MS / 1000}s — recovering (attempt ${initAttempt})`);
    if (initAttempt > MAX_INIT_RETRIES) {
      log(`Max init retries reached — bridge giving up`);
      emitEvent("error", { message: "WhatsApp bridge stuck before authentication after retries", fatal: true });
      try { await client.destroy(); } catch (_) {}
      process.exit(1);
    }
    // Tear down the dead Chromium and try fresh
    try { await client.destroy(); } catch (err) { log(`destroy during retry: ${err.message}`); }
    client = buildClient();
    attachHandlers(client);
    startClientWithWatchdog();
  }, INIT_WATCHDOG_MS);

  log(`Initializing WhatsApp client... (attempt ${initAttempt}/${MAX_INIT_RETRIES + 1})`);
  try {
    await client.initialize();
  } catch (err) {
    if (initWatchdog) { clearTimeout(initWatchdog); initWatchdog = null; }
    log(`Initialize error: ${err.message}`);
    if (initAttempt > MAX_INIT_RETRIES) {
      emitEvent("error", { message: err.message, fatal: true });
      process.exit(1);
    }
    try { await client.destroy(); } catch (_) {}
    client = buildClient();
    attachHandlers(client);
    return startClientWithWatchdog();
  }
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

        const chats = await client.getChats();
        let matches = chats
          .filter((ch) => {
            const name = (ch.name || "").toLowerCase();
            const number = (ch.id && ch.id.user) || "";
            return name.includes(query) || number.includes(query);
          })
          .slice(0, 20)
          .map((ch) => {
            const serialized = ch.id._serialized;
            // LID-based chats don't have a phone number — ch.id.user is
            // the LID's user portion, which fails as a `to` value in
            // send_message. Surface the full JID instead so the agent
            // round-trips a valid send target through `number`.
            const isLid = serialized.endsWith("@lid");
            return {
              id: serialized,
              name: ch.name || "",
              number: isLid ? serialized : ((ch.id && ch.id.user) || ""),
              is_group: ch.isGroup,
            };
          });

        if (matches.length === 0) {
          // Fallback: reach into the page's Store. Filter runs in-page
          // so only the matches cross the RPC boundary.
          try {
            matches = await client.pupPage.evaluate((q) => {
              const query = (q || "").toLowerCase();
              return window.Store.Contact.getModelsArray()
                .filter((c) => {
                  const name = (c.pushname || c.name || c.formattedName || "").toLowerCase();
                  const number = (c.id && c.id.user) || "";
                  return name.includes(query) || number.includes(query);
                })
                .slice(0, 20)
                .map((c) => {
                  const serialized = c.id._serialized;
                  const isLid = serialized.endsWith("@lid");
                  return {
                    id: serialized,
                    name: c.pushname || c.name || c.formattedName || "",
                    number: isLid ? serialized : ((c.id && c.id.user) || ""),
                    is_group: c.isGroup,
                  };
                });
            }, args.name || "");
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

      case "logout": {
        // Full disconnect: logs out of WhatsApp server-side AND wipes the
        // LocalAuth data on disk, so the next connect demands a fresh QR.
        // Without this, ``client.destroy()`` alone leaves the session
        // restorable and the bridge auto-reconnects on next start.
        log("Logout requested");
        emitResponse(id, { success: true });
        try {
          if (client) await client.logout();
          log("Logged out");
        } catch (err) {
          log(`Logout error: ${err.message}`);
          // Fall through to destroy/exit — even a partial logout is
          // better than leaving the bridge running.
          try { if (client) await client.destroy(); } catch (_) {}
        }
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
        if (sent?.id?._serialized) ownSentIds.add(sent.id._serialized);
        emitResponse(id, {
          success: true,
          message_id: sent?.id?._serialized || null,
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
          message_id: sent?.id?._serialized || null,
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
        if (sent?.id?._serialized) ownSentIds.add(sent.id._serialized);
        emitResponse(id, { success: true, message_id: sent?.id?._serialized || null });
        break;
      }

      case "edit_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await client.getMessageById(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        await msg.edit(args.new_body);
        emitResponse(id, { success: true, message_id: args.message_id });
        break;
      }

      case "delete_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await client.getMessageById(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        await msg.delete(args.everyone === true);
        emitResponse(id, { success: true, message_id: args.message_id, deleted_for_everyone: args.everyone === true });
        break;
      }

      case "forward_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await client.getMessageById(args.message_id);
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
        const msg = await client.getMessageById(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        await msg.react(args.emoji || "");  // empty string removes the reaction
        emitResponse(id, { success: true, message_id: args.message_id, emoji: args.emoji });
        break;
      }

      case "star_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await client.getMessageById(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        if (args.starred === false) await msg.unstar(); else await msg.star();
        emitResponse(id, { success: true, message_id: args.message_id, starred: args.starred !== false });
        break;
      }

      case "download_message_media": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await client.getMessageById(args.message_id);
        if (!msg) { emitResponse(id, { success: false, error: "Message not found" }); return; }
        if (!msg.hasMedia) { emitResponse(id, { success: false, error: "Message has no media" }); return; }
        const media = await msg.downloadMedia();
        if (!media) { emitResponse(id, { success: false, error: "Media download failed" }); return; }
        emitResponse(id, {
          success: true,
          mimetype: media.mimetype,
          filename: media.filename || "",
          data_b64: media.data,
        });
        break;
      }

      case "get_quoted_message": {
        if (!isReady) { emitResponse(id, { success: false, error: "Client not ready" }); return; }
        const msg = await client.getMessageById(args.message_id);
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

// Start: build the initial client, attach handlers, run with watchdog.
// startClientWithWatchdog() handles its own retries + final exit on failure.
client = buildClient();
attachHandlers(client);
startClientWithWatchdog();
