#!/usr/bin/env node
// feishu-memory-recall: Cross-group memory and event sharing for OpenClaw
//
// Commands:
//   recall --user <id> [--hours 24]       Search messages from a specific user across all groups
//   search --keyword <text> [--hours 24]  Search messages by keyword across all groups
//   digest [--hours 6]                    Generate a digest of all recent activity across groups
//   log-event --source <name> --event <text>  Write to RECENT_EVENTS.md
//   sync-groups                           Auto-discover active groups from gateway sessions
//   add-group --id <id> --name <name>     Manually track a group
//   list-groups                           Show tracked groups
//
const { program } = require('commander');
const fs = require('fs');
const path = require('path');

try {
    require('dotenv').config({ path: path.resolve(__dirname, '../../.env') });
} catch (e) {}

const MEMORY_DIR = path.resolve(__dirname, '../../memory');
const WORKSPACE = path.resolve(__dirname, '../..');
const TOKEN_PATH = path.join(MEMORY_DIR, 'feishu_token.json');
const GROUPS_FILE = path.join(MEMORY_DIR, 'active_groups.json');
const RECENT_EVENTS = path.join(WORKSPACE, 'RECENT_EVENTS.md');
const SESSIONS_FILE = path.join(
    process.env.HOME || '/home/' + (process.env.USER || 'user'),
    '.openclaw/agents/main/sessions/sessions.json'
);

const FEISHU_API = 'https://open.feishu.cn/open-apis';

// --- Auth ---
async function getToken() {
    // Try cached token first
    if (fs.existsSync(TOKEN_PATH)) {
        try {
            const data = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8'));
            if (data.token && data.expire > Date.now() / 1000) return data.token;
        } catch (e) {}
    }
    // Try to get fresh token
    const appId = process.env.FEISHU_APP_ID;
    const appSecret = process.env.FEISHU_APP_SECRET;
    if (!appId || !appSecret) throw new Error('No valid token. Set FEISHU_APP_ID and FEISHU_APP_SECRET.');

    const res = await fetch(`${FEISHU_API}/auth/v3/tenant_access_token/internal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: appId, app_secret: appSecret })
    });
    const data = await res.json();
    if (data.code !== 0) throw new Error(`Token error: ${data.msg}`);

    const tokenData = { token: data.tenant_access_token, expire: Math.floor(Date.now() / 1000) + data.expire - 60 };
    fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokenData));
    return tokenData.token;
}

// --- Feishu API helpers ---
async function fetchMessages(token, chatId, hours = 24) {
    const messages = [];
    const cutoff = Date.now() - hours * 3600 * 1000;
    try {
        const url = `${FEISHU_API}/im/v1/messages?container_id_type=chat&container_id=${chatId}&page_size=50&sort_type=ByCreateTimeDesc`;
        const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
        const data = await res.json();
        if (data.code === 0 && data.data && data.data.items) {
            for (const item of data.data.items) {
                if (parseInt(item.create_time) < cutoff) break;
                messages.push(item);
            }
        } else if (data.code !== 0) {
            console.error(`[Fetch Error] Chat ${chatId}: ${data.msg} (code ${data.code})`);
        }
    } catch (e) {
        console.error(`[Network Error] Chat ${chatId}: ${e.message}`);
    }
    return messages;
}

function parseContent(msg) {
    try {
        const body = JSON.parse(msg.body.content);
        if (msg.msg_type === 'text') return body.text;
        if (msg.msg_type === 'image') return '[Image]';
        if (msg.msg_type === 'post') return `[Post: ${body.title || ''}] ${(body.content || []).flat().map(c => c.text || '').join(' ').slice(0, 100)}`;
        if (msg.msg_type === 'interactive') return '[Card]';
        return `[${msg.msg_type}]`;
    } catch (e) {
        return '[Unparseable]';
    }
}

function formatTime(ts) {
    return new Date(parseInt(ts)).toISOString().replace('T', ' ').substring(5, 16);
}

// --- Group management ---
function loadGroups() {
    try {
        if (fs.existsSync(GROUPS_FILE)) return JSON.parse(fs.readFileSync(GROUPS_FILE, 'utf8'));
    } catch (e) {}
    return [];
}

function saveGroups(groups) {
    fs.writeFileSync(GROUPS_FILE, JSON.stringify(groups, null, 2));
}

// --- Commands ---
async function recall(userId, hours) {
    const token = await getToken();
    const groups = loadGroups();
    const found = [];

    // Check P2P
    try {
        const res = await fetch(`${FEISHU_API}/im/v1/chats?user_id_type=open_id`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await res.json();
        if (data.code === 0 && data.data) {
            const msgs = await fetchMessages(token, data.data.chat_id, hours);
            msgs.filter(m => m.sender.id === userId).forEach(m => {
                found.push({ source: 'DM', time: m.create_time, text: parseContent(m) });
            });
        }
    } catch (e) {}

    // Check all tracked groups
    for (const group of groups) {
        const msgs = await fetchMessages(token, group.id, hours);
        msgs.filter(m => m.sender.id === userId).forEach(m => {
            found.push({ source: group.name, time: m.create_time, text: parseContent(m) });
        });
    }

    found.sort((a, b) => parseInt(a.time) - parseInt(b.time));
    console.log(JSON.stringify({ user: userId, hours, count: found.length, messages: found.map(m => ({
        time: formatTime(m.time), source: m.source, text: m.text
    })) }, null, 2));
}

async function search(keyword, hours) {
    const token = await getToken();
    const groups = loadGroups();
    const found = [];
    const kw = keyword.toLowerCase();

    for (const group of groups) {
        const msgs = await fetchMessages(token, group.id, hours);
        msgs.forEach(m => {
            const text = parseContent(m);
            if (text.toLowerCase().includes(kw)) {
                found.push({ source: group.name, time: m.create_time, sender: m.sender.id, text });
            }
        });
    }

    found.sort((a, b) => parseInt(a.time) - parseInt(b.time));
    console.log(JSON.stringify({ keyword, hours, count: found.length, matches: found.map(m => ({
        time: formatTime(m.time), source: m.source, text: m.text.slice(0, 200)
    })) }, null, 2));
}

async function digest(hours) {
    const token = await getToken();
    const groups = loadGroups();
    const summary = [];

    for (const group of groups) {
        const msgs = await fetchMessages(token, group.id, hours);
        if (msgs.length === 0) continue;

        const senders = new Set(msgs.map(m => m.sender.id));
        const textMsgs = msgs.filter(m => m.msg_type === 'text' || m.msg_type === 'post');
        const preview = textMsgs.slice(0, 3).map(m => parseContent(m).slice(0, 80));

        summary.push({
            group: group.name,
            chat_id: group.id,
            messages: msgs.length,
            participants: senders.size,
            preview
        });
    }

    summary.sort((a, b) => b.messages - a.messages);
    console.log(JSON.stringify({ hours, groups_active: summary.length, digest: summary }, null, 2));
}

function logEvent(source, eventText) {
    const now = new Date();
    const time = now.toISOString().substring(11, 16);
    const line = `- [${time} UTC] [${source}] ${eventText}`;

    // Append to RECENT_EVENTS.md
    let content = '';
    if (fs.existsSync(RECENT_EVENTS)) {
        content = fs.readFileSync(RECENT_EVENTS, 'utf8');
    }
    const lines = content.split('\n');
    // Find the insertion point (after header, before old entries)
    const headerEnd = lines.findIndex(l => l.startsWith('<!-- Format:'));
    const insertAt = headerEnd >= 0 ? headerEnd + 1 : lines.length;
    lines.splice(insertAt + 1, 0, line);

    // Prune to 50 event lines max
    const eventLines = lines.filter(l => l.startsWith('- ['));
    if (eventLines.length > 50) {
        const toRemove = eventLines.slice(0, eventLines.length - 50);
        for (const rm of toRemove) {
            const idx = lines.indexOf(rm);
            if (idx >= 0) lines.splice(idx, 1);
        }
    }

    fs.writeFileSync(RECENT_EVENTS, lines.join('\n'));

    // Also append to daily log
    const dailyFile = path.join(MEMORY_DIR, now.toISOString().split('T')[0] + '.md');
    fs.appendFileSync(dailyFile, line + '\n');

    console.log(`Logged: ${line}`);
}

function syncGroups() {
    if (!fs.existsSync(SESSIONS_FILE)) {
        console.error('sessions.json not found at', SESSIONS_FILE);
        return;
    }

    const sessions = JSON.parse(fs.readFileSync(SESSIONS_FILE, 'utf8'));
    const existing = loadGroups();
    const existingIds = new Set(existing.map(g => g.id));
    let added = 0;

    for (const key of Object.keys(sessions)) {
        // Match feishu group sessions: agent:main:feishu:group:oc_xxxxx
        const match = key.match(/feishu:group:(oc_[a-f0-9]+)/);
        if (match && !existingIds.has(match[1])) {
            existing.push({ id: match[1], name: match[1].slice(0, 12) + '...' });
            existingIds.add(match[1]);
            added++;
        }
    }

    saveGroups(existing);
    console.log(JSON.stringify({ total: existing.length, added, groups: existing }, null, 2));
}

// --- Exports ---
module.exports = {
    recall,
    search,
    digest,
    logEvent,
    syncGroups,
    loadGroups,
    saveGroups
};

// --- CLI ---
if (require.main === module) {
    program
        .command('recall')
        .description('Find recent messages from a user across all groups')
        .requiredOption('-u, --user <id>', 'User Open ID')
        .option('--hours <n>', 'Lookback hours', '24')
        .action(async (opts) => { await recall(opts.user, Number(opts.hours)); });

    program
        .command('search')
        .description('Search messages by keyword across all groups')
        .requiredOption('-k, --keyword <text>', 'Search keyword')
        .option('--hours <n>', 'Lookback hours', '24')
        .action(async (opts) => { await search(opts.keyword, Number(opts.hours)); });

    program
        .command('digest')
        .description('Generate activity digest across all tracked groups')
        .option('--hours <n>', 'Lookback hours', '6')
        .action(async (opts) => { await digest(Number(opts.hours)); });

    program
        .command('log-event')
        .description('Write an event to RECENT_EVENTS.md and daily log')
        .requiredOption('-s, --source <name>', 'Event source (group name or context)')
        .requiredOption('-e, --event <text>', 'Event description')
        .option('--content <text>', 'Event description (alias)')
        .action((opts) => { 
            const evt = opts.event || opts.content;
            if (!evt) {
                console.error("Error: --event or --content required");
                process.exit(1);
            }
            logEvent(opts.source, evt); 
        });

    program
        .command('sync-groups')
        .description('Auto-discover Feishu groups from gateway sessions')
        .action(() => { syncGroups(); });

    program
        .command('add-group')
        .description('Manually track a Feishu group')
        .requiredOption('-i, --id <id>', 'Chat ID (oc_...)')
        .requiredOption('-n, --name <name>', 'Group name')
        .action((opts) => {
            const groups = loadGroups().filter(g => g.id !== opts.id);
            groups.push({ id: opts.id, name: opts.name });
            saveGroups(groups);
            console.log(`Added: ${opts.name} (${opts.id})`);
        });

    program
        .command('list-groups')
        .description('Show all tracked groups')
        .action(() => { console.log(JSON.stringify(loadGroups(), null, 2)); });

    program.parse();
}
