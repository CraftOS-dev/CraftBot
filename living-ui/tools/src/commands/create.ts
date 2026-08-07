/**
 * lui create <name> [--description "…"] [--dir <parent>] [--port <n>]
 * Scaffold a project from the blueprint: copy, vendor kit, substitute
 * placeholders (spec P4/D6).
 */
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { writeSystemHashes } from '../lib/hashes.ts';
import { vendorKitInto } from '../lib/kit.ts';
import { log } from '../lib/log.ts';
import { blueprintDir, examplesDir, pinnedPbVersion } from '../lib/paths.ts';
import { ensurePbBinary } from './pb.ts';

/**
 * Machine superuser (spec B5): lets tooling/agents administer the project via
 * PB APIs. Credentials live only in the project-local, 0600, gitignored
 * `.superuser` file — never in code.
 */
async function bootstrapSuperuser(projectDir: string): Promise<void> {
  const pbBin = await ensurePbBinary();
  const pbDir = join(projectDir, 'pb');
  const email = 'agent@lui.local';
  const password = randomBytes(18).toString('base64url');

  execFileSync(
    pbBin,
    [
      'superuser',
      'upsert',
      email,
      password,
      '--dir',
      join(pbDir, 'pb_data'),
      '--migrationsDir',
      join(pbDir, 'pb_migrations'),
      '--hooksDir',
      join(pbDir, 'pb_hooks'),
    ],
    { stdio: 'pipe' },
  );

  writeFileSync(join(projectDir, '.superuser'), JSON.stringify({ email, password }) + '\n', {
    mode: 0o600,
  });
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
}

function argValue(args: string[], flag: string): string | undefined {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : undefined;
}

export async function run(args: string[]): Promise<number> {
  const name = args.find((a) => !a.startsWith('--'));
  if (name === undefined) {
    log.error(
      'Usage: lui create <name> [--description "…"] [--dir <parent>] [--port <n>] [--auth none|multi-user]',
    );
    return 1;
  }
  const description = argValue(args, '--description') ?? `${name} — a Living UI app`;
  const parent = argValue(args, '--dir') ?? examplesDir();
  const port = Number(argValue(args, '--port') ?? 8090);
  const authMode = argValue(args, '--auth') ?? 'none';
  if (authMode !== 'none' && authMode !== 'multi-user') {
    log.error(`--auth must be "none" or "multi-user" (got "${authMode}")`);
    return 1;
  }
  const jsonOutput = args.includes('--json');
  const style = argValue(args, '--style');
  // Provenance: which CraftBot created this app (empty when scaffolded
  // outside CraftBot, e.g. by hand via the CLI).
  const craftbotVersion = argValue(args, '--craftbot-version') ?? '';

  const slug = slugify(name);
  const id = argValue(args, '--id') ?? randomBytes(4).toString('hex');
  const folder = argValue(args, '--folder') ?? slug;
  const projectDir = join(parent, folder);

  if (existsSync(projectDir)) {
    log.error(`Already exists: ${projectDir}`);
    return 1;
  }

  log.step(`Scaffolding "${name}" → ${projectDir}`);
  cpSync(blueprintDir(), projectDir, { recursive: true });

  log.step('Vendoring kit…');
  const kitV = vendorKitInto(projectDir);

  const substitutions: Record<string, string> = {
    '{{PROJECT_ID}}': id,
    '{{PROJECT_NAME}}': name,
    '{{PROJECT_DESCRIPTION}}': description,
    '{{PORT}}': String(port),
    '{{CREATED_AT}}': new Date().toISOString(),
    '{{PB_VERSION}}': pinnedPbVersion(),
    '{{KIT_VERSION}}': kitV,
    '{{CRAFTBOT_VERSION}}': craftbotVersion,
    '{{AUTH_MODE}}': authMode,
    '{{AUTH_RULE}}': authMode === 'multi-user' ? '@request.auth.id != ""' : '',
  };

  for (const rel of [
    'manifest.json',
    'LIVING_UI.md',
    join('frontend', 'index.html'),
    join('frontend', 'src', 'config.gen.ts'),
    join('pb', 'pb_migrations', '1700000000_init_items.js'),
  ]) {
    const file = join(projectDir, rel);
    const isJson = rel.endsWith('.json');
    let text = readFileSync(file, 'utf8');
    for (const [token, value] of Object.entries(substitutions)) {
      // JSON files need string-escaped values (descriptions can be multiline).
      text = text.replaceAll(token, isJson ? JSON.stringify(value).slice(1, -1) : value);
    }
    writeFileSync(file, text);
  }

  // Stamp the default style pack (host theme still overrides at runtime).
  if (style !== undefined && style !== 'craftbot') {
    const idx = join(projectDir, 'frontend', 'index.html');
    writeFileSync(
      idx,
      readFileSync(idx, 'utf8').replace('data-theme="light"', `data-theme="light" data-style="${style}"`),
    );
  }

  // Port must be a number in the manifest; the pipeline string keeps it inline.
  const manifestPath = join(projectDir, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as { port: unknown };
  manifest.port = port;
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');

  // Unique package name so npm workspaces don't collide.
  const pkgPath = join(projectDir, 'frontend', 'package.json');
  const pkg = JSON.parse(readFileSync(pkgPath, 'utf8')) as { name: string };
  pkg.name = `lui-app-${slug}`;
  writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n');

  // Pre-create the log files agents read while debugging — an empty file
  // reads cleanly; a missing one derails the diagnosis.
  mkdirSync(join(projectDir, 'logs'), { recursive: true });
  for (const logName of ['frontend_console.log', 'pocketbase.log']) {
    const logFile = join(projectDir, 'logs', logName);
    if (!existsSync(logFile)) writeFileSync(logFile, '');
  }

  log.step('Bootstrapping superuser (initializes pb_data + applies migrations)…');
  await bootstrapSuperuser(projectDir);

  // Canonize system files LAST — after every tooling edit (spec §11 step 5).
  writeSystemHashes(projectDir);

  if (jsonOutput) {
    log.raw(JSON.stringify({ path: projectDir, id, slug, port, authMode, kitVersion: kitV }));
  } else {
    log.ok(`Created ${projectDir} (id ${id}, port ${port}, auth ${authMode}, kit ${kitV})`);
    log.raw(`Next: npm install && node tools/src/cli.ts dev ${projectDir}`);
  }
  return 0;
}
