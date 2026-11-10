// Real, unchanged protocol 0.1 adapter, with disposable owner-only app data.
import { pathToFileURL } from 'node:url';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
const [entry, dir, home] = process.argv.slice(2);
const { createA2App, createA2AppServer, MemoryBinding } = await import(pathToFileURL(entry));
const token = 'disposable-local-owner';
const app = createA2App(new MemoryBinding({
  appId: 'local-task-fixture', appName: 'Local task fixture', authMode: 'none',
  entities: { notes: { module: 'desk', fields: [{ name: 'title', type: 'string' }], seed: [{ id: 'note1', title: 'Round-trip note' }] } },
}), {
  modules: [{ name: 'desk' }], events: [{ type: 'note.ask' }], capabilities: { summarize: {} },
  credentials: [{ token, credentialId: 'local-owner', principal: 'owner', scopes: ['*'] }],
});
const server = createA2AppServer(app);
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port, base = `http://127.0.0.1:${port}`;
mkdirSync(dir, { recursive: true }); mkdirSync(home, { recursive: true });
const manifest = { id: 'local-task-fixture', name: 'Local task fixture', agentAppVersion: '0.1.0', adapterVersion: '0.2.0', authMode: 'none', modules: [{ name: 'desk' }], pipeline: { install: '', build: '', start: '', health: '/api/_a2app' }, port };
writeFileSync(join(dir, 'manifest.json'), JSON.stringify(manifest));
writeFileSync(join(dir, '.agent-token'), token);
writeFileSync(join(home, 'registry.json'), JSON.stringify({ version: 1, apps: [{ id: manifest.id, name: manifest.name, path: dir, port }] }));
console.log(JSON.stringify({ port, id: manifest.id, base }));
for await (const line of createInterface({ input: process.stdin })) {
  const input = JSON.parse(line);
  if (input.op === 'task') console.log(JSON.stringify(app.trigger({ type: 'note.ask', capability: 'summarize', payload: { question: 'Read my note' } })));
  else if (input.op === 'status') console.log(JSON.stringify(app.store.getTask(input.id)));
}
server.close();
