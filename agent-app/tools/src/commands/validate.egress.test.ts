/**
 * collectEgressHosts — the three scan outcomes (EXTERNAL-DATA-PLAN §4):
 *   1. literal / helper-passed URLs → hosts recorded
 *   2. no $http.send → nothing recorded
 *   3. $http.send with zero literal hosts in the file → unresolved (file:line)
 * Run: node --test tools/src/commands/validate.egress.test.ts
 */
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { collectEgressHosts } from './validate.ts';

function project(files: Record<string, string>): string {
  const dir = mkdtempSync(join(tmpdir(), 'lui-egress-'));
  mkdirSync(join(dir, 'pb', 'pb_hooks'), { recursive: true });
  for (const [name, content] of Object.entries(files)) {
    writeFileSync(join(dir, 'pb', 'pb_hooks', name), content);
  }
  return dir;
}

test('literal url in $http.send → host recorded', () => {
  const dir = project({
    'ops.pb.js': `
const OPEN_METEO = 'https://api.open-meteo.com/v1/forecast';
routerAdd('POST', '/api/ops/weather-refresh', (e) => {
  const res = $http.send({ url: OPEN_METEO + '?latitude=1', method: 'GET', timeout: 20 });
  return e.json(200, res.json);
});`,
  });
  try {
    const scan = collectEgressHosts(dir);
    assert.deepEqual(scan.hosts, ['api.open-meteo.com']);
    assert.deepEqual(scan.unresolved, []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('helper-passed url (yahoo.js shape) → hosts from call-site literals, no false warning', () => {
  const dir = project({
    'yahoo.js': `
function yahooGet(url) {
  const res = $http.send({ url: url, method: 'GET', timeout: 20 });
  return res.json;
}
function chart(symbol) {
  return yahooGet('https://query1.finance.yahoo.com/v8/finance/chart/' + symbol);
}
function quote(symbol) {
  return yahooGet(\`https://query2.finance.yahoo.com/v7/finance/quote?symbols=\${symbol}\`);
}`,
  });
  try {
    const scan = collectEgressHosts(dir);
    assert.deepEqual(scan.hosts, ['query1.finance.yahoo.com', 'query2.finance.yahoo.com']);
    assert.deepEqual(scan.unresolved, []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('no egress, loopback-only, comments, and system files → empty scan', () => {
  const dir = project({
    'ops.pb.js': `
// docs: https://should-not-count.example.com/guide
routerAdd('POST', '/api/ops/items/clear-done', (e) => {
  const records = e.app.findRecordsByFilter('items', 'done = true', '', 0, 0);
  return e.json(200, { cleared: records.length });
});`,
    'local.pb.js': `
routerAdd('GET', '/api/ops/self', (e) => {
  const res = $http.send({ url: 'http://127.0.0.1:3100/api/health', method: 'GET', timeout: 5 });
  return e.json(200, res.json);
});`,
    '_system_like.js': `
const res = $http.send({ url: 'https://system-module-not-scanned.example.com', method: 'GET' });`,
  });
  try {
    const scan = collectEgressHosts(dir);
    assert.deepEqual(scan.hosts, []);
    // local.pb.js has $http.send and zero non-loopback literals → its own
    // egress set is empty, but the loopback literal exists, so it is NOT dark.
    assert.deepEqual(scan.unresolved, []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('split module (URLs in helper, $http passed as param) → hosts recorded, no warning', () => {
  // The observed weather_tracker_d8fb248a shape: the module holds the literal
  // but never mentions $http.send; the caller sends but holds no literal.
  const dir = project({
    'weather.js': `
const OPEN_METEO = 'https://api.open-meteo.com/v1/forecast';
function refreshWeather(app, http) {
  const res = http.send({ url: OPEN_METEO + '?latitude=1', method: 'GET', timeout: 20 });
  return res.json;
}
module.exports = { refreshWeather };`,
    'ops.pb.js': `
routerAdd('POST', '/api/ops/weather-refresh', (e) => {
  const weather = require(\`\${__hooks}/weather.js\`);
  const res = $http.send;  // reference without a literal in this file
  return e.json(200, { current: weather.refreshWeather(e.app, $http) });
});`,
  });
  try {
    const scan = collectEgressHosts(dir);
    assert.deepEqual(scan.hosts, ['api.open-meteo.com']);
    assert.deepEqual(scan.unresolved, []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('callIntegration + callAction literals → integrations/actions derived (grant sources)', () => {
  const dir = project({
    'ops.pb.js': `
routerAdd('POST', '/api/ops/send-reminder', (e) => {
  const bridge = require(\`\${__hooks}/_craftbot_bridge.js\`);
  const res = bridge.callAction('send_gmail', { to: 'x', subject: 's', body: 'b' }, { confirmIrreversible: true });
  const res2 = bridge.callIntegration("slack", 'POST', '/api/chat.postMessage', {});
  const res3 = bridge.callAction("send_slack_message", { channel: '#g', message: 'm' });
  return e.json(200, { ok: true });
});`,
  });
  try {
    const scan = collectEgressHosts(dir);
    assert.deepEqual(scan.integrations, ['slack']);
    assert.deepEqual(scan.actions, ['send_gmail', 'send_slack_message']);
    assert.deepEqual(scan.hosts, []); // bridge calls are not raw egress
    assert.deepEqual(scan.unresolved, []); // and not dark — no $http.send here
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('computed destination with no literal anywhere → unresolved with file:line', () => {
  const dir = project({
    'relay.pb.js': `
routerAdd('POST', '/api/ops/relay', (e) => {
  const target = e.requestInfo().body.target;
  const res = $http.send({ url: target, method: 'POST', timeout: 10 });
  return e.json(200, res.json);
});`,
  });
  try {
    const scan = collectEgressHosts(dir);
    assert.deepEqual(scan.hosts, []);
    assert.equal(scan.unresolved.length, 1);
    assert.equal(scan.unresolved[0]?.file, 'relay.pb.js');
    assert.equal(scan.unresolved[0]?.line, 4);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
