/**
 * lui validate <project> — the validation gate (spec §11, D7 scope for M1):
 *   1. tsc --noEmit        (types)
 *   2. vite build          (build; lands in pb/pb_public)
 *   3. migrations apply    (against a FRESH temp pb_data)
 *   4. operations.json     (structural validation)
 * Machine-readable failures: one line per error, `step: message`.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { verifySystemHashes } from '../lib/hashes.ts';
import { log } from '../lib/log.ts';
import { ensurePbBinary } from './pb.ts';

interface GateError {
  step: string;
  message: string;
}

/**
 * Dependency policy (agent-editable package.json, bounded trust):
 * - `dependencies` may contain ANY package from the npm registry — agents
 *   need real libraries and a curated list can never keep up.
 * - The supply-chain door that curation was guarding is closed differently:
 *   installs run with `--ignore-scripts` (see lib/npm.ts), so a malicious or
 *   typosquatted package cannot execute code at install time. Package code
 *   still runs inside the app itself once imported and bundled.
 * - Version specs must be plain semver (optionally ^ or ~) — never git/url/
 *   file specs, which sidestep the registry (and its scripts policy) entirely.
 * - `devDependencies` and `scripts` are frozen (build tooling is platform-
 *   owned); lifecycle script keys are forbidden outright.
 */
const BASELINE_DEPS = new Set([
  '@radix-ui/react-dialog',
  'class-variance-authority',
  'clsx',
  'pocketbase',
  'react',
  'react-dom',
  'tailwind-merge',
]);


const BASELINE_DEV_DEPS = new Set([
  '@tailwindcss/vite',
  '@types/react',
  '@types/react-dom',
  '@vitejs/plugin-react',
  'tailwindcss',
  'typescript',
  'vite',
]);

const BASELINE_SCRIPTS: Record<string, string> = {
  dev: 'vite',
  build: 'tsc -p . && vite build',
  typecheck: 'tsc -p .',
};

const SEMVER_SPEC = /^[~^]?\d+\.\d+\.\d+(-[\w.]+)?$/;

/** Problems with a project's frontend/package.json under the policy above.
 *  Exported for unit tests. */
export function checkDependencies(projectDir: string): string[] {
  const pkgPath = join(projectDir, 'frontend', 'package.json');
  if (!existsSync(pkgPath)) return ['frontend/package.json is missing'];
  let pkg: Record<string, unknown>;
  try {
    pkg = JSON.parse(readFileSync(pkgPath, 'utf8')) as Record<string, unknown>;
  } catch (e) {
    return [`frontend/package.json is not valid JSON: ${(e as Error).message}`];
  }
  const problems: string[] = [];

  // Any npm package is allowed; only the SPEC is policed (installs run with
  // --ignore-scripts, so registry packages cannot run code at install time).
  const deps = (pkg.dependencies ?? {}) as Record<string, string>;
  for (const [name, spec] of Object.entries(deps)) {
    if (!SEMVER_SPEC.test(spec)) {
      problems.push(
        `dependency '${name}' uses spec '${spec}' — only plain semver (e.g. "^1.9.4") is allowed, never git/url/file specs`,
      );
    }
  }

  const devDeps = (pkg.devDependencies ?? {}) as Record<string, string>;
  for (const name of Object.keys(devDeps)) {
    if (!BASELINE_DEV_DEPS.has(name)) {
      problems.push(
        `devDependencies are frozen (build tooling is platform-owned); remove '${name}'`,
      );
    }
  }

  const scripts = (pkg.scripts ?? {}) as Record<string, string>;
  for (const [name, cmd] of Object.entries(scripts)) {
    if (/^(pre|post)?(install|prepare|prepublish)/.test(name)) {
      problems.push(
        `script '${name}' is a lifecycle hook — forbidden (runs arbitrary code at install)`,
      );
    } else if (BASELINE_SCRIPTS[name] !== undefined && BASELINE_SCRIPTS[name] !== cmd) {
      problems.push(
        `script '${name}' was changed — the platform owns build scripts (expected: '${BASELINE_SCRIPTS[name]}')`,
      );
    }
  }
  for (const name of Object.keys(BASELINE_SCRIPTS)) {
    if (scripts[name] === undefined) problems.push(`script '${name}' is missing (platform-owned)`);
  }
  return problems;
}


interface Operation {
  name?: unknown;
  description?: unknown;
  system?: unknown;
  params?: unknown;
  executor?: {
    type?: unknown;
    method?: unknown;
    path?: unknown;
    collection?: unknown;
    action?: unknown;
  };
}

/** Extract routerAdd(method, path) declarations from every pb_hooks file. */
function collectHookRoutes(projectDir: string): Set<string> {
  const hooksDir = join(projectDir, 'pb', 'pb_hooks');
  const routes = new Set<string>();
  if (!existsSync(hooksDir)) return routes;
  for (const name of readdirSync(hooksDir)) {
    if (!name.endsWith('.pb.js')) continue;
    const source = readFileSync(join(hooksDir, name), 'utf8');
    const re = /routerAdd\(\s*['"](GET|POST|PUT|PATCH|DELETE)['"]\s*,\s*['"]([^'"]+)['"]/g;
    for (const match of source.matchAll(re)) {
      routes.add(`${match[1]} ${match[2]}`);
    }
  }
  return routes;
}

/**
 * Reject the PocketBase transaction footgun (spec A2APP-PLAN §3.2).
 *
 * `runInTransaction(txApp => …)` hands you a transaction handle. Using the
 * OUTER app handle (`e.app` / `$app`) inside that callback does not merely
 * misbehave:
 *   - a READ returns stale data silently
 *   - a WRITE **deadlocks the whole process, permanently**
 * and the app keeps answering `GET /api/health` with 200 throughout, so the
 * host's own health check cannot see it. One line in one hook turns the app
 * into a read-only zombie.
 *
 * The correct handle is the callback's parameter. This is a cheap structural
 * check for a failure that is otherwise near-impossible to diagnose from
 * outside.
 */
function checkTransactionHandles(projectDir: string): void {
  const hooksDir = join(projectDir, 'pb', 'pb_hooks');
  if (!existsSync(hooksDir)) return;

  for (const name of readdirSync(hooksDir)) {
    if (!name.endsWith('.js')) continue;
    const source = readFileSync(join(hooksDir, name), 'utf8');

    // Find each runInTransaction( … ) callback body by brace matching, so a
    // nested function or object literal does not end the scan early.
    const opener = /runInTransaction\s*\(/g;
    for (const start of source.matchAll(opener)) {
      const from = (start.index ?? 0) + start[0].length;
      let depth = 1;
      let i = from;
      for (; i < source.length && depth > 0; i++) {
        if (source[i] === '(') depth++;
        else if (source[i] === ')') depth--;
      }
      const body = source.slice(from, i);
      const offender = /\b(e\.app|\$app)\s*\./.exec(body);
      if (offender !== null) {
        const line = source.slice(0, from + offender.index).split('\n').length;
        throw new Error(
          `${name}:${line}: "${offender[1]}" used inside runInTransaction — use the ` +
            `callback's own transaction handle instead. Writing through the outer ` +
            `handle DEADLOCKS the process permanently, and /api/health keeps ` +
            `returning 200 so nothing detects it.`
        );
      }
    }
  }
}

/**
 * Append the offending SOURCE to every error that names a location, in any
 * gate step — agents fix the wrong thing when they only see line numbers.
 * Handles `path(line,col)` (tsc), `path:line:col` (esbuild/vite), and
 * `failed to apply migration <file>` (PocketBase, no line info → whole file).
 */
function annotateErrors(output: string, searchDirs: string[]): string {
  const readSource = (rel: string): string | null => {
    for (const dir of searchDirs) {
      const abs = join(dir, rel);
      if (existsSync(abs)) return readFileSync(abs, 'utf8');
    }
    return null;
  };

  const annotateAt = (line: string, rel: string, lineNo: number, col: number): string => {
    const content = readSource(rel);
    if (content === null) return line;
    const source = content.split('\n')[lineNo - 1] ?? '';
    const start = Math.max(0, col - 60);
    const snippet = source.slice(start, start + 140);
    const caret = ' '.repeat(Math.min(Math.max(col - 1 - start, 0), 139)) + '^ THE OFFENDING EXPRESSION IS HERE (col ' + col + ')';
    return `${line}\n    | ${snippet}\n    | ${caret}`;
  };

  return output
    .split('\n')
    .map((line) => {
      const paren = line.match(/^(.+?)\((\d+),(\d+)\): /);
      if (paren !== null) {
        return annotateAt(line, paren[1] ?? '', Number(paren[2]), Number(paren[3]));
      }
      const colon = line.match(/([\w./-]+\.(?:tsx?|css|js))[(:](\d+)[,:](\d+)/);
      if (colon !== null) {
        return annotateAt(line, colon[1] ?? '', Number(colon[2]), Number(colon[3]));
      }
      const migration = line.match(/failed to apply migration ([\w.-]+\.js)/);
      if (migration !== null) {
        const content = readSource(join('pb', 'pb_migrations', migration[1] ?? ''));
        if (content !== null) {
          const head = content.split('\n').slice(0, 80).join('\n');
          return `${line}\n    --- ${migration[1]} (the failing migration) ---\n${head}`;
        }
      }
      return line;
    })
    .join('\n');
}

function runStep(errors: GateError[], step: string, fn: () => void): void {
  try {
    fn();
    log.ok(step);
  } catch (err) {
    const message =
      err instanceof Error && 'stdout' in err
        ? String((err as Error & { stdout?: unknown }).stdout ?? err.message)
        : err instanceof Error
          ? err.message
          : String(err);
    errors.push({ step, message: message.trim().slice(0, 4000) });
    log.error(`${step} failed`);
  }
}

function validateOps(projectDir: string): void {
  const raw = readFileSync(join(projectDir, 'operations.json'), 'utf8');
  const parsed = JSON.parse(raw) as { opsVersion?: unknown; operations?: unknown };
  if (parsed.opsVersion !== 1) throw new Error('opsVersion must be 1');
  if (!Array.isArray(parsed.operations)) throw new Error('operations must be an array');

  const routes = collectHookRoutes(projectDir);
  const coveredRoutes = new Set<string>();
  const seen = new Set<string>();

  for (const op of parsed.operations as Operation[]) {
    if (typeof op.name !== 'string' || !/^[a-z][a-z0-9._-]{0,63}$/.test(op.name)) {
      throw new Error(`invalid op name: ${JSON.stringify(op.name)} (see spec/operations.schema.json)`);
    }
    if (seen.has(op.name)) throw new Error(`duplicate op name: ${op.name}`);
    seen.add(op.name);
    if (typeof op.description !== 'string' || op.description === '') {
      throw new Error(`${op.name}: description required`);
    }

    const type = op.executor?.type;
    if (type === 'crud') {
      if (typeof op.executor?.collection !== 'string' || typeof op.executor?.action !== 'string') {
        throw new Error(`${op.name}: crud executor needs collection + action`);
      }
      continue;
    }
    if (type !== 'http' && type !== 'job') {
      throw new Error(`${op.name}: executor.type must be http|crud|job`);
    }
    const method = op.executor?.method;
    const path = op.executor?.path;
    if (typeof method !== 'string' || typeof path !== 'string' || !path.startsWith('/api/')) {
      throw new Error(`${op.name}: http/job executor needs method + /api/... path`);
    }

    // O3 structural check: non-system ops must resolve to a declared hook route.
    // System entries may point at PB built-ins (e.g. /api/health).
    const key = `${method} ${path}`;
    coveredRoutes.add(key);
    if (op.system !== true && !routes.has(key)) {
      throw new Error(
        `${op.name}: no pb_hooks route matches "${key}" — declare the route with routerAdd or fix the op`,
      );
    }
  }

  // O3 coverage: hook routes not covered by any op are warnings, not errors.
  for (const route of routes) {
    const path = route.split(' ')[1] ?? '';
    if (path.startsWith('/api/_')) continue; // system plumbing (_ops, _console, _jobs)
    if (!coveredRoutes.has(route)) {
      log.warn(`route not declared as an operation: ${route} (agents can't discover it)`);
    }
  }
}

export async function run(args: string[]): Promise<number> {
  const projectDir = args[0];
  if (projectDir === undefined || !existsSync(join(projectDir, 'manifest.json'))) {
    log.error('Usage: lui validate <project-dir>   (must contain manifest.json)');
    return 1;
  }

  const frontendDir = join(projectDir, 'frontend');
  const errors: GateError[] = [];

  // Windows: npm is npm.cmd, which Node refuses to spawn without a shell.
  const isWin = process.platform === 'win32';
  const npmRun = (script: string): void => {
    execFileSync(isWin ? 'npm.cmd' : 'npm', ['run', script], {
      cwd: frontendDir, stdio: 'pipe', encoding: 'utf8', shell: isWin,
    });
  };

  runStep(errors, 'dependencies (semver specs)', () => {
    const problems = checkDependencies(projectDir);
    if (problems.length > 0) {
      throw new Error(
        `frontend/package.json violates the dependency policy:\n${problems.join('\n')}\n` +
          `Any npm package may go in "dependencies" with a plain semver pin; ` +
          `devDependencies and scripts are platform-owned.`,
      );
    }
  });

  runStep(errors, 'types (tsc --noEmit)', () => npmRun('typecheck'));

  runStep(errors, 'build (vite)', () => npmRun('build'));

  const pbBin = await ensurePbBinary();
  runStep(errors, 'migrations (fresh pb_data)', () => {
    const tempData = mkdtempSync(join(tmpdir(), 'lui-migrate-'));
    try {
      // NOTE: `pocketbase migrate up` exits 0 even when a migration fails —
      // it only PRINTS the error. Scan output; never trust the exit code.
      const out = execFileSync(
        pbBin,
        [
          'migrate',
          'up',
          '--dir',
          tempData,
          '--migrationsDir',
          join(projectDir, 'pb', 'pb_migrations'),
          '--hooksDir',
          join(projectDir, 'pb', 'pb_hooks'),
        ],
        { stdio: 'pipe', encoding: 'utf8' },
      );
      const failure = out.split('\n').find((l) => /^\s*Error[:\s]/.test(l));
      if (failure !== undefined) {
        throw new Error(
          `${failure.trim()}\nHint: relation fields need the target collection's ID — ` +
            `save the target first, then use app.findCollectionByNameOrId('<name>').id`,
        );
      }
    } finally {
      rmSync(tempData, { recursive: true, force: true });
    }
  });

  runStep(errors, 'operations.json (structure)', () => validateOps(projectDir));

  runStep(errors, 'hooks (transaction handles)', () =>
    checkTransactionHandles(projectDir)
  );

  runStep(errors, 'ownership (system files unmodified)', () => {
    const drift = verifySystemHashes(projectDir);
    const problems: string[] = [
      ...drift.modified.map((p) => `modified: ${p}`),
      ...drift.missing.map((p) => `deleted: ${p}`),
      ...drift.added.map((p) => `added: ${p}`),
    ];
    if (problems.length > 0) {
      throw new Error(
        `system-managed files changed outside tooling (spec P1):\n${problems.join('\n')}\n` +
          `If a kit upgrade is intended, run kit-sync; agent edits belong in app-owned paths.`,
      );
    }
  });

  // Enrich every located error with its source before reporting.
  for (const e of errors) {
    e.message = annotateErrors(e.message, [frontendDir, projectDir]);
  }

  if (errors.length > 0) {
    log.raw('');
    for (const e of errors) log.raw(`${e.step}: ${e.message.split('\n').slice(0, 15).join('\n')}`);
    log.error(`Gate: ${errors.length} step(s) failed`);
    return 1;
  }
  log.ok('Gate: all steps passed');
  return 0;
}
