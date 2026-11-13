// Private host transport for protocol 0.1 local-owner tasks. Never exposed as
// an agent action. Reuse the pinned framework's credential reader unchanged.
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const [pkg, app, expectedId, mode] = process.argv.slice(2);
const { loadProject, readAgentToken, adminClient } = await import(pathToFileURL(join(pkg, 'dist/lib/project.js')).href);
try {
  const project = loadProject(app);
  if (project.manifest.id !== expectedId) throw Error();
  if (mode === 'pending') {
    const client = await adminClient(project);
    const response = await client.pollTasks('submitted');
    if (!response.ok || !Array.isArray(response.json?.tasks)) throw Error();
    process.stdout.write(JSON.stringify(response.json.tasks.map(t => ({ id: t.id, capability: t.request?.capability }))));
  } else {
    if (project.manifest.authMode !== 'none') throw Error();
    const token = readAgentToken(project.dir);
    if (!token) throw Error();
    // Captured in memory by CraftBot; never logged, persisted or shown to a model.
    process.stdout.write(token);
  }
} catch {
  process.stderr.write('The app connection is unavailable.');
  process.exitCode = 1;
}
