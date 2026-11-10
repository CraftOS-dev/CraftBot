// Disposable real upstream adapter fixture. No patched framework code.
import { pathToFileURL } from 'node:url';
import { createServer } from 'node:net';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
const [entry, dir, home] = process.argv.slice(2);
const { createA2App, createA2AppServer, MemoryBinding } = await import(pathToFileURL(entry));
const port = await new Promise(resolve => { const s = createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); }); });
const base = `http://127.0.0.1:${port}`, admin = 'fixture-owner-token';
const app = createA2App(new MemoryBinding({
  appId: 'craftbot-task-test', appName: 'Native task test', authMode: 'multi-user',
  entities: { notes: { module: 'desk', ownedBy: 'owner', fields: [{ name: 'title', type: 'string', required: true }, { name: 'owner', type: 'string', readOnly: true }], seed: [] } },
}), {
  modules: [{ name: 'desk' }], allowedOrigins: [base], events: [{ type: 'note.ask' }],
  capabilities: { summarize: { scopes: ['data:notes:read'] } },
  credentials: [{ token: admin, credentialId: 'owner-credential', principal: 'owner', scopes: ['*'], admin: true }],
});
const server = createA2AppServer(app);
await new Promise(resolve => server.listen(port, '127.0.0.1', resolve));
const call = (method, path, headers = {}, body) => app.handle({ method, path, query: {}, headers: { host: `127.0.0.1:${port}`, ...headers }, body });
async function account(name, role) {
  const invited = (await call('POST', '/api/_a2app/invites', { 'x-a2app-token': admin }, { role })).json;
  const accepted = await call('POST', `/api/_a2app/invites/${invited.code}`, { origin: base }, { name, login: name.toLowerCase(), password: 'fixture long password' });
  return { id: accepted.json.id, session: { origin: base, cookie: accepted.headers['set-cookie'].split(';')[0] } };
}
const owner = await account('Owner', 'owner'), member = await account('Member', 'member');
await call('POST', '/api/collections/notes/records', owner.session, { title: 'Private owner note' });
await call('POST', '/api/collections/notes/records', member.session, { title: 'Member note' });
mkdirSync(dir, { recursive: true }); mkdirSync(home, { recursive: true });
const manifest = { id: 'craftbot-task-test', name: 'Native task test', agentAppVersion: '0.2.0', adapterVersion: '0.2.0', authMode: 'multi-user', modules: [{ name: 'desk' }], capabilities: { summarize: {} }, pipeline: { install: '', build: '', start: '', health: '/api/_a2app' }, port };
writeFileSync(join(dir, 'manifest.json'), JSON.stringify(manifest));
writeFileSync(join(dir, '.agent-token'), admin);
writeFileSync(join(home, 'registry.json'), JSON.stringify({ version: 1, apps: [{ id: manifest.id, name: manifest.name, path: dir, port }] }));
console.log(JSON.stringify({ port, id: manifest.id, member: member.id, base }));
for await (const line of createInterface({ input: process.stdin })) {
  const input = JSON.parse(line);
  if (input.op === 'task') console.log(JSON.stringify(app.trigger({ type: 'note.ask', capability: 'summarize', principal: member.id, payload: { question: 'Read my notes' } })));
  else if (input.op === 'status') console.log(JSON.stringify(app.store.getTask(input.id)));
  else if (input.op === 'cancel') { const task = app.store.getTask(input.id); task.status = 'canceled'; app.store.saveTask(task); console.log('{}'); }
  else if (input.op === 'claim-change') { const task = app.store.getTask(input.id); task.claim.claimedAt = new Date(Date.now() + 1000).toISOString(); app.store.saveTask(task); console.log('{}'); }
}
server.close();
