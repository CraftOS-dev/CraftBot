// Thin host binding: upstream owns identity, credentials, task claims and delivery.
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const [pkg, origin, expectedId, mode, endpoint] = process.argv.slice(2);
const load = file => import(pathToFileURL(join(pkg, 'dist/lib', file)).href);
try {
  const { connect, verifyRemote } = await load('target.js');
  const { client, target } = await connect(origin);
  if (target.kind !== 'remote' || target.appId !== expectedId) throw Error();
  const identity = await client.identity();
  const who = await client.request('GET', '/api/_a2app/whoami');
  if (!who.ok || !who.json?.principal) throw Error();
  if (mode === 'info') {
    process.stdout.write(JSON.stringify({ identity, who: who.json }));
  } else if (mode === 'credential') {
    const { credentialFor } = await load('remote.js');
    const token = credentialFor(origin, expectedId);
    if (!token) throw Error();
    process.stdout.write(token);
  } else if (mode === 'pending') {
    const result = await client.pollTasks('submitted');
    if (!result.ok || !Array.isArray(result.json?.tasks)) throw Error();
    process.stdout.write(JSON.stringify(result.json.tasks.map(t => ({ id: t.id, capability: t.request?.capability }))));
  } else if (mode === 'pump') {
    const { pumpLoop, DEFAULT_INTERVAL_MS, DEFAULT_TASK_TIMEOUT_MS } = await load('bridge.js');
    // Check the pinned identity again before each poll, including after outages.
    const poll = client.pollTasks.bind(client);
    client.pollTasks = async (...args) => { await verifyRemote(client, target); return poll(...args); };
    const ctx = {
      client, profile: { id: 'craftbot' },
      route: { mode: 'inbound', url: endpoint, tokenEnv: 'CRAFTBOT_BRIDGE_TOKEN' },
      prompt: { appRef: origin, appName: target.appName, appId: expectedId, closesOnExit: false, cwdIsApp: false },
      taskTimeoutMs: DEFAULT_TASK_TIMEOUT_MS, capabilities: null, dryRun: false,
      taskCredentials: identity.protocol !== '0.1',
    };
    // The host owns process lifetime; logs contain no authority and need not accumulate.
    const { log } = await load('log.js');
    for (const key of ['info', 'warn', 'error', 'ok', 'step']) log[key] = () => {};
    await pumpLoop(ctx, DEFAULT_INTERVAL_MS, () => false);
  } else throw Error();
} catch {
  process.stderr.write('The app connection is unavailable or access has changed.');
  process.exitCode = 1;
}
