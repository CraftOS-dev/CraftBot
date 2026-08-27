/**
 * lui validate <project> — the validation gate (spec §11, D7 scope for M1):
 *   1. tsc --noEmit        (types)
 *   2. vite build          (build; lands in pb/pb_public)
 *   3. migrations apply    (against a FRESH temp pb_data)
 *   4. operations.json     (structural validation)
 * Machine-readable failures: one line per error, `step: message`.
 *
 * Steps 1-2 are the wall-time cost (68-200s) and are skipped when the build
 * inputs are unchanged since the last successful build (see the build-currency
 * fast path below); every other step runs on every call.
 */
import { createHash } from 'node:crypto';
import { execFileSync, spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileMatchesCanon, recordFileHash, verifySystemHashes } from '../lib/hashes.ts';
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
const BASELINE_DEV_DEPS = new Set([
  '@tailwindcss/vite',
  '@types/react',
  '@types/react-dom',
  '@vitejs/plugin-react',
  'tailwindcss',
  'typescript',
  'vite',
  'vite-plugin-istanbul', // dev-build coverage for scoped walk-verify (LUI_COVERAGE=1)
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
 * Egress scan (spec EXTERNAL-DATA-PLAN §4): derive the app's outbound surface.
 *
 * `capabilities.external_hosts` in manifest.json is written by the GATE, never
 * declared by the agent — same lifecycle as `.lui/system-hashes.json`. One
 * JSON field answers "what does this app talk to?" for build output, users,
 * and (later) marketplace review. Born from the weather-tracker incident,
 * where an app whose requirements promised live API data shipped
 * `Math.random()` and nothing could see the difference.
 *
 * Scan rules:
 * - Agent hook files only. `_*.js` system modules are hash-verified and talk
 *   only to the loopback bridge via env vars — scanning them would produce
 *   false "undeterminable destination" warnings.
 * - Hosts come from `https?://` string literals in EVERY agent hook file
 *   (comments stripped) — not only files containing `$http.send`. Literal
 *   collection, not per-call URL resolution, because real hooks split code
 *   across helpers: trading-view's yahoo.js takes `url` as a parameter, and
 *   an observed weather app kept its URLs in a module that received `$http`
 *   itself as a parameter — the send and the literal need not share a file.
 * - Only a PROJECT with `$http.send` and no URL literal anywhere is genuinely
 *   dark → each such call site is reported as unresolved (file:line).
 *   Warning today; marketplace ingest is expected to reject it (tier 2).
 */
export interface EgressScan {
  hosts: string[];
  /** CraftBot integrations used via bridge.callIntegration('<id>', …) —
   *  derived from code the same way hosts are. The manifest grant the bridge
   *  fails closed on is WRITTEN from this: the code is the declaration.
   *  (Observed live: a weather app's email feature was dead because nothing
   *  in the platform could mint `capabilities.integrations` at all.) */
  integrations: string[];
  /** CraftBot ACTIONS used via bridge.callAction('<name>', …) — the
   *  preferred integration surface (semantic params, CraftBot's own
   *  implementation). capabilities.actions is written from this. */
  actions: string[];
  unresolved: { file: string; line: number }[];
}

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '0.0.0.0', '::1', '[::1]']);

export function collectEgressHosts(projectDir: string): EgressScan {
  const hooksDir = join(projectDir, 'pb', 'pb_hooks');
  const hosts = new Set<string>();
  const integrations = new Set<string>();
  const actions = new Set<string>();
  const darkCallSites: { file: string; line: number }[] = [];
  let projectSawLiteral = false;
  if (!existsSync(hooksDir)) return { hosts: [], integrations: [], actions: [], unresolved: [] };

  for (const name of readdirSync(hooksDir)) {
    if (!name.endsWith('.js') || name.startsWith('_')) continue;
    const source = readFileSync(join(hooksDir, name), 'utf8');

    // Strip block comments and whole-line // comments so a doc link does not
    // count as egress. (Trailing // comments are left alone — cutting them
    // naively would truncate the `//` inside 'https://…' string literals.)
    const code = source
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '');

    // Loopback literals (an app calling its own API) are not egress, but they
    // DO prove destinations are visible.
    let fileSawLiteral = false;
    for (const m of code.matchAll(/['"`](https?:\/\/[^'"`\n$]+)/g)) {
      try {
        const host = new URL(m[1] ?? '').hostname.toLowerCase();
        if (host === '') continue;
        fileSawLiteral = true;
        if (!LOOPBACK_HOSTS.has(host)) hosts.add(host);
      } catch {
        /* not a parseable URL — ignore */
      }
    }
    if (fileSawLiteral) projectSawLiteral = true;

    // Bridge integrations: the first argument of callIntegration is the id.
    for (const m of code.matchAll(/callIntegration\(\s*['"`]([a-z][a-z0-9_]*)['"`]/g)) {
      integrations.add(m[1] ?? '');
    }
    // Bridge actions: the first argument of callAction is the action name.
    for (const m of code.matchAll(/callAction\(\s*['"`]([a-z][a-z0-9_]*)['"`]/g)) {
      actions.add(m[1] ?? '');
    }

    // Call sites whose own file holds no literal — dark ONLY if the whole
    // project turns out literal-free (decided after the loop).
    if (!fileSawLiteral && source.includes('$http.send')) {
      for (const call of source.matchAll(/\$http\.send\s*\(/g)) {
        const line = source.slice(0, call.index ?? 0).split('\n').length;
        darkCallSites.push({ file: name, line });
      }
    }
  }
  return {
    hosts: [...hosts].sort(),
    integrations: [...integrations].filter(Boolean).sort(),
    actions: [...actions].filter(Boolean).sort(),
    unresolved: projectSawLiteral ? [] : darkCallSites,
  };
}

/**
 * Agent-owned hooks must not touch the trigger queue (spec TRIGGERS-PLAN).
 * Observed live 2026-08-06: a fix iteration wired a hook that self-claimed
 * `chat.summary` requests and wrote a board-dump as the "result" — an
 * in-process hook beats the session-dispatched agent every time, so the app
 * permanently shadowed the real agent while every walk passed. The queue is
 * the REACTING agent's surface: apps fire via `_triggers_lib.fire()` (which
 * never names the collection) and render results via frontend realtime —
 * they never read, claim, or answer their own requests. The state-machine
 * guard cannot enforce this (hooks use e.app.save(), which bypasses router
 * middleware), so the gate must.
 */
export function checkTriggerQueueOwnership(projectDir: string): string[] {
  const hooksDir = join(projectDir, 'pb', 'pb_hooks');
  if (!existsSync(hooksDir)) return [];
  const problems: string[] = [];
  for (const name of readdirSync(hooksDir)) {
    if (!name.endsWith('.js') || name.startsWith('_')) continue;
    const source = readFileSync(join(hooksDir, name), 'utf8');
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    for (const m of code.matchAll(/agent_requests/g)) {
      const line = code.slice(0, m.index ?? 0).split('\n').length;
      problems.push(
        `${name}:${line}: agent hooks must not touch the agent_requests queue — ` +
          `it is the reacting AGENT's surface. Fire with ` +
          "require(`${__hooks}/_triggers_lib.js`).fire(e.app, '<name>', {…}, 'hook') " +
          `and render results via the frontend's realtime subscription. An app ` +
          `that claims or answers its own requests shadows the real agent.`,
      );
    }
  }
  return problems;
}

/**
 * triggers.json (spec TRIGGERS-PLAN): the app→agent declaration. Structure
 * errors here are protocol errors — a trigger with no instruction can never
 * be reacted to, and a bad param spec makes every fire unvalidatable. The
 * declared names are the source `capabilities.triggers` is derived from, so
 * this must be strict: the bridge fails closed on the derived list.
 */
export function validateTriggersManifest(projectDir: string): string[] {
  const file = join(projectDir, 'triggers.json');
  if (!existsSync(file)) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(file, 'utf8'));
  } catch (err) {
    return [`triggers.json is not valid JSON: ${err instanceof Error ? err.message : String(err)}`];
  }
  const triggers = (parsed as { triggers?: unknown }).triggers;
  if (triggers === undefined) return ['triggers.json must have a top-level "triggers" object'];
  if (typeof triggers !== 'object' || triggers === null || Array.isArray(triggers)) {
    return ['"triggers" must be an object keyed by trigger name'];
  }
  const problems: string[] = [];
  const NAME = /^[a-z][a-z0-9._-]{0,63}$/;
  const PARAM_TYPES = new Set(['string', 'number', 'boolean']);
  for (const [name, def] of Object.entries(triggers as Record<string, unknown>)) {
    const at = `triggers.${name}`;
    if (!NAME.test(name)) {
      problems.push(`${at}: name must match ${NAME} (lowercase, like operation names)`);
    }
    if (typeof def !== 'object' || def === null || Array.isArray(def)) {
      problems.push(`${at}: must be an object`);
      continue;
    }
    const d = def as Record<string, unknown>;
    if (typeof d.instruction !== 'string' || d.instruction.trim() === '') {
      problems.push(`${at}: "instruction" (non-empty string) is required — it is what the agent executes`);
    }
    if (d.description !== undefined && typeof d.description !== 'string') {
      problems.push(`${at}: "description" must be a string`);
    }
    if (d.cooldown_seconds !== undefined) {
      const cd = d.cooldown_seconds;
      if (typeof cd !== 'number' || !Number.isInteger(cd) || cd < 0) {
        problems.push(`${at}: "cooldown_seconds" must be a non-negative integer`);
      }
    }
    if (d.params !== undefined) {
      if (typeof d.params !== 'object' || d.params === null || Array.isArray(d.params)) {
        problems.push(`${at}: "params" must be an object keyed by param name`);
      } else {
        for (const [pname, pspec] of Object.entries(d.params as Record<string, unknown>)) {
          if (typeof pspec !== 'object' || pspec === null || Array.isArray(pspec)) {
            problems.push(`${at}.params.${pname}: must be an object with a "type"`);
            continue;
          }
          const p = pspec as Record<string, unknown>;
          if (!PARAM_TYPES.has(String(p.type))) {
            problems.push(
              `${at}.params.${pname}: "type" must be one of string|number|boolean (operations.json param shape)`,
            );
          }
          if (p.enum !== undefined && !Array.isArray(p.enum)) {
            problems.push(`${at}.params.${pname}: "enum" must be an array`);
          }
        }
      }
    }
    const known = new Set(['description', 'instruction', 'params', 'cooldown_seconds']);
    for (const key of Object.keys(d)) {
      if (!known.has(key)) problems.push(`${at}: unknown key "${key}"`);
    }
  }
  return problems;
}

/** Declared trigger names — what `capabilities.triggers` is derived from.
 *  Empty on a missing or STRUCTURALLY INVALID manifest: a declaration the
 *  structure step rejects must not mint capability entries (the fire gate
 *  fails closed on this list, so over-minting would be the actual hole). */
export function collectDeclaredTriggers(projectDir: string): string[] {
  const file = join(projectDir, 'triggers.json');
  if (!existsSync(file)) return [];
  if (validateTriggersManifest(projectDir).length > 0) return [];
  try {
    const parsed = JSON.parse(readFileSync(file, 'utf8')) as { triggers?: Record<string, unknown> };
    const triggers = parsed.triggers;
    if (typeof triggers !== 'object' || triggers === null || Array.isArray(triggers)) return [];
    return Object.keys(triggers).sort();
  } catch {
    return [];
  }
}

/** Frontend must not call external hosts directly (CORS breaks standalone
 *  deploys; anything secret would be public). Warning-only: matches only
 *  fetch('https://… — plain href links in JSX are legitimate. */
function collectFrontendEgress(projectDir: string): { file: string; line: number; host: string }[] {
  const appDir = join(projectDir, 'frontend', 'src', 'app');
  const found: { file: string; line: number; host: string }[] = [];
  if (!existsSync(appDir)) return found;
  for (const rel of readdirSync(appDir, { recursive: true }) as string[]) {
    if (!/\.(ts|tsx)$/.test(rel)) continue;
    const abs = join(appDir, rel);
    if (statSync(abs).isDirectory()) continue;
    const source = readFileSync(abs, 'utf8');
    for (const m of source.matchAll(/fetch\(\s*['"`](https?:\/\/[^'"`\n$]+)/g)) {
      try {
        const host = new URL(m[1] ?? '').hostname.toLowerCase();
        if (LOOPBACK_HOSTS.has(host)) continue;
        const line = source.slice(0, m.index ?? 0).split('\n').length;
        found.push({ file: rel, line, host });
      } catch {
        /* ignore */
      }
    }
  }
  return found;
}

/** Write the derived host list into manifest.json's `capabilities` and
 *  re-record its canon hash. Skips (with a warning) when the manifest does
 *  not match canon — the tooling must never write on top of, and thereby
 *  launder, an agent edit; the ownership step will report the tampering. */
function syncEgressManifest(
  projectDir: string,
  hosts: string[],
  integrations: string[],
  actions: string[],
  triggers: string[],
): void {
  const manifestPath = join(projectDir, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as Record<string, unknown>;
  const capabilities = { ...((manifest.capabilities as Record<string, unknown>) ?? {}) };
  const same = (key: string, next: string[]): boolean => {
    const current = Array.isArray(capabilities[key]) ? (capabilities[key] as string[]) : [];
    return current.length === next.length && current.every((v, idx) => v === next[idx]);
  };
  if (
    same('external_hosts', hosts) &&
    same('integrations', integrations) &&
    same('actions', actions) &&
    same('triggers', triggers)
  ) {
    return;
  }

  const clean = fileMatchesCanon(projectDir, 'manifest.json');
  if (clean === false) {
    log.warn('manifest.json differs from canon — skipping egress write (see ownership step)');
    return;
  }
  if (clean === null) {
    log.warn('no hash canon yet — skipping egress manifest write (create/kit-sync records it)');
    return;
  }

  if (hosts.length === 0) delete capabilities.external_hosts;
  else capabilities.external_hosts = hosts;
  if (integrations.length === 0) delete capabilities.integrations;
  else capabilities.integrations = integrations;
  if (actions.length === 0) delete capabilities.actions;
  else capabilities.actions = actions;
  // The bridge's fire gate fails closed on this list; deriving it from
  // triggers.json (agent-owned) into the manifest (canon-hashed) is what
  // makes "declared at build time" enforceable at fire time.
  if (triggers.length === 0) delete capabilities.triggers;
  else capabilities.triggers = triggers;
  if (Object.keys(capabilities).length === 0) delete manifest.capabilities;
  else manifest.capabilities = capabilities;

  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
  recordFileHash(projectDir, 'manifest.json');
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
      // "apply" = migrate-up failure; "run" = the registration-time PANIC a
      // syntactically-loaded-but-broken migration triggers. Checked FIRST:
      // panic lines also carry goja's synthetic `pb.js:7:9` location, which
      // the generic path:line:col matcher would grab (and fail to resolve).
      const migration = line.match(/failed to (?:apply|run) migration ([\w.-]+\.js)/);
      if (migration !== null) {
        const content = readSource(join('pb', 'pb_migrations', migration[1] ?? ''));
        if (content !== null) {
          const head = content.split('\n').slice(0, 80).join('\n');
          return `${line}\n    --- ${migration[1]} (the failing migration) ---\n${head}`;
        }
      }
      const paren = line.match(/^(.+?)\((\d+),(\d+)\): /);
      if (paren !== null) {
        return annotateAt(line, paren[1] ?? '', Number(paren[2]), Number(paren[3]));
      }
      const colon = line.match(/([\w./-]+\.(?:tsx?|css|js))[(:](\d+)[,:](\d+)/);
      if (colon !== null) {
        return annotateAt(line, colon[1] ?? '', Number(colon[2]), Number(colon[3]));
      }
      return line;
    })
    .join('\n');
}

function recordStepFailure(errors: GateError[], step: string, err: unknown): void {
  // A spawned tool's failure can live in stdout OR stderr — PocketBase
  // PANICS to stderr with an empty stdout (e.g. a bad migration at hook
  // registration). Reading only stdout produced a blank error, and an agent
  // told "step failed: <nothing>" retries blind until it gives up. Never
  // emit an empty message.
  let message = '';
  if (err instanceof Error) {
    const spawned = err as Error & { stdout?: unknown; stderr?: unknown };
    message = [spawned.stdout, spawned.stderr]
      .map((s) => String(s ?? '').trim())
      .filter((s) => s !== '')
      .join('\n');
    if (message === '') message = err.message;
  } else {
    message = String(err);
  }
  if (message.trim() === '') message = `${step}: failed with no output (exit status only)`;
  errors.push({ step, message: message.trim().slice(0, 4000) });
  log.error(`${step} failed`);
}

function runStep(errors: GateError[], step: string, fn: () => void): void {
  try {
    fn();
    log.ok(step);
  } catch (err) {
    recordStepFailure(errors, step, err);
  }
}

async function runStepAsync(
  errors: GateError[],
  step: string,
  fn: () => Promise<void>,
): Promise<void> {
  try {
    await fn();
    log.ok(step);
  } catch (err) {
    recordStepFailure(errors, step, err);
  }
}

/**
 * Run `pocketbase migrate up` with the output WATCHED as it streams.
 *
 * A Go-side panic wedges PocketBase — alive, silent, never exiting — so the
 * hard timeout stays as the backstop. But the panic announces itself in the
 * FIRST lines of output ("RECOVERED FROM PANIC"), and waiting out the
 * remaining ~118 s buys nothing: observed live (kanban_board_1bb64990,
 * 2026-08-04), two wedged fix iterations cost 120 s each with the panic
 * line already printed. Kill the moment it appears; the caller's panic scan
 * turns the captured output into the agent-facing error.
 *
 * Resolves with combined stdout+stderr on exit or panic-kill; rejects only
 * on the silent timeout (with partial output) or a spawn failure.
 */
function runMigrateWatched(
  bin: string,
  args: string[],
  timeoutMs: number,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    let settled = false;
    let killedWhy: 'panic' | 'timeout' | null = null;

    const timer = setTimeout(() => {
      if (killedWhy === null) {
        killedWhy = 'timeout';
        child.kill('SIGKILL');
      }
    }, timeoutMs);

    const finish = (fn: () => void): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn();
    };

    const watch = (chunk: Buffer): void => {
      out += chunk.toString('utf8');
      if (killedWhy === null && /RECOVERED FROM PANIC|^panic:/m.test(out)) {
        killedWhy = 'panic';
        child.kill('SIGKILL');
      }
    };
    child.stdout?.on('data', watch);
    child.stderr?.on('data', watch);
    child.on('error', (err) => finish(() => reject(err)));
    child.on('close', () => {
      finish(() => {
        if (killedWhy === 'timeout') {
          const partial = out.trim();
          reject(
            new Error(
              `migrations ran for >${Math.round(timeoutMs / 1000)}s and were killed — ` +
                'a migration or hook is blocking the process. Known cause: ' +
                '`new Record(<id string>)` nil-panics PocketBase and WEDGES it ' +
                'without exiting; the Record constructor needs the Collection ' +
                "OBJECT (`new Record(app.findCollectionByNameOrId('name'))`)." +
                (partial === '' ? '' : `\nlast output:\n${partial.slice(-2000)}`),
            ),
          );
        } else {
          resolve(out);
        }
      });
    });
  });
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

// ---------------------------------------------------------------------------
// Build-currency fast path
//
// `tsc --noEmit` + `vite build` are 90%+ of the gate's wall time (measured
// 68-200s per app) and reproduce identical output when their inputs are
// unchanged. Fingerprint every build input under frontend/; when it matches
// the last SUCCESSFUL build and pb_public still holds that output, skip both
// steps. Every other gate step still runs, and the host's headless `verify`
// remains the backstop: a stale or corrupt cached build fails to mount there,
// which forces a full rebuild on the next launch (the fingerprint is only
// written after a clean build, never after a failed one).
// ---------------------------------------------------------------------------

const BUILD_FP_FILE = join('.lui', 'build-fingerprint.txt');
const BUILD_INPUT_IGNORE = new Set(['node_modules', 'dist', '.vite', '.turbo', '.cache']);

/** SHA-256 over every build input under frontend/ (src, package.json, the
 *  lockfile, tsconfig, vite/tailwind config, index.html, public assets),
 *  excluding node_modules and any build output. Order-independent: relative
 *  paths are sorted and both the path and the bytes feed the hash. Returns
 *  null when frontend/ can't be read — a null is never treated as "current". */
function computeBuildFingerprint(frontendDir: string): string | null {
  if (!existsSync(frontendDir)) return null;
  const files: string[] = [];
  const walk = (dir: string, rel: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const childRel = rel === '' ? entry.name : `${rel}/${entry.name}`;
      if (entry.isDirectory()) {
        if (BUILD_INPUT_IGNORE.has(entry.name)) continue;
        walk(join(dir, entry.name), childRel);
      } else if (entry.isFile()) {
        files.push(childRel);
      }
    }
  };
  try {
    walk(frontendDir, '');
    files.sort();
    const h = createHash('sha256');
    // A coverage-instrumented (dev) build is a different artifact from a
    // plain one — the flag is a build input.
    h.update(`LUI_COVERAGE=${process.env['LUI_COVERAGE'] ?? ''}\0`);
    for (const rel of files) {
      h.update(rel);
      h.update('\0');
      h.update(readFileSync(join(frontendDir, rel)));
      h.update('\0');
    }
    return h.digest('hex');
  } catch {
    return null;
  }
}

function readBuildFingerprint(projectDir: string): string | null {
  try {
    return readFileSync(join(projectDir, BUILD_FP_FILE), 'utf8').trim();
  } catch {
    return null;
  }
}

function writeBuildFingerprint(projectDir: string, fp: string): void {
  try {
    mkdirSync(join(projectDir, '.lui'), { recursive: true });
    writeFileSync(join(projectDir, BUILD_FP_FILE), fp + '\n');
  } catch (err) {
    log.warn(
      `could not record build fingerprint (next launch will rebuild): ${(err as Error).message}`,
    );
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

  // Skip tsc + vite build when the inputs are byte-for-byte the last-built
  // state AND pb_public still holds that output; otherwise build and record
  // the fingerprint — but only when BOTH steps pass, so a failed build never
  // marks itself current. tsc --noEmit and vite build write nothing under
  // frontend/, so the fingerprint taken before the build still describes the
  // inputs afterward.
  const builtIndex = join(projectDir, 'pb', 'pb_public', 'index.html');
  const buildFp = computeBuildFingerprint(frontendDir);
  const buildCurrent =
    buildFp !== null && existsSync(builtIndex) && readBuildFingerprint(projectDir) === buildFp;

  if (buildCurrent) {
    log.ok('types (tsc --noEmit) — skipped (build inputs unchanged)');
    log.ok('build (vite) — skipped (build inputs unchanged)');
  } else {
    const errorsBefore = errors.length;
    runStep(errors, 'types (tsc --noEmit)', () => npmRun('typecheck'));
    runStep(errors, 'build (vite)', () => npmRun('build'));
    if (errors.length === errorsBefore && buildFp !== null && existsSync(builtIndex)) {
      writeBuildFingerprint(projectDir, buildFp);
    }
  }

  const pbBin = await ensurePbBinary();
  await runStepAsync(errors, 'migrations (fresh pb_data)', async () => {
    const tempData = mkdtempSync(join(tmpdir(), 'lui-migrate-'));
    try {
      // NOTE: `pocketbase migrate up` exits 0 even when a migration fails —
      // it only PRINTS the error. Scan output; never trust the exit code.
      // NOTE: the output is streamed and watched (runMigrateWatched): a
      // recognized panic kills the process in ~seconds, the 120 s timeout
      // remains the backstop for silent wedges.
      const out = await runMigrateWatched(
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
        120_000,
      );
      const failure = out.split('\n').find((l) => /^\s*Error[:\s]/.test(l));
      if (failure !== undefined) {
        throw new Error(
          `${failure.trim()}\nHint: relation fields need the target collection's ID — ` +
            `save the target first, then use app.findCollectionByNameOrId('<name>').id`,
        );
      }
      // A Go panic that PocketBase "recovered" is still a broken migration —
      // and the usual trigger is new Record(<string>) instead of the object.
      const panicked = out.split('\n').find((l) => /RECOVERED FROM PANIC|^panic:/.test(l));
      if (panicked !== undefined) {
        throw new Error(
          `${panicked.trim()}\nA migration crashed PocketBase internally. Known cause: ` +
            `new Record(<id string>) — the Record constructor needs the Collection ` +
            `OBJECT: new Record(app.findCollectionByNameOrId('name')).`,
        );
      }
    } finally {
      rmSync(tempData, { recursive: true, force: true });
    }
  });

  runStep(errors, 'operations.json (structure)', () => validateOps(projectDir));

  runStep(errors, 'triggers.json (structure)', () => {
    const problems = validateTriggersManifest(projectDir);
    if (problems.length > 0) throw new Error(problems.join('\n'));
  });

  runStep(errors, 'trigger queue ownership (hooks)', () => {
    const problems = checkTriggerQueueOwnership(projectDir);
    if (problems.length > 0) throw new Error(problems.join('\n'));
  });

  runStep(errors, 'hooks (transaction handles)', () =>
    checkTransactionHandles(projectDir)
  );

  runStep(errors, 'egress (external hosts)', () => {
    const scan = collectEgressHosts(projectDir);
    for (const u of scan.unresolved) {
      log.warn(
        `${u.file}:${u.line}: outbound call with undeterminable destination — ` +
          `keep the base URL as a string literal in this file so it can be recorded`,
      );
    }
    for (const f of collectFrontendEgress(projectDir)) {
      log.warn(
        `frontend/src/app/${f.file}:${f.line}: direct fetch to ${f.host} — ` +
          `external calls belong in pb_hooks (CORS breaks standalone deploys; ` +
          `anything secret would be public)`,
      );
    }
    const triggers = collectDeclaredTriggers(projectDir);
    syncEgressManifest(projectDir, scan.hosts, scan.integrations, scan.actions, triggers);
    log.info(scan.hosts.length === 0 ? 'no external hosts' : `talks to: ${scan.hosts.join(', ')}`);
    if (scan.integrations.length > 0) {
      log.info(`uses integrations: ${scan.integrations.join(', ')}`);
    }
    if (scan.actions.length > 0) {
      log.info(`uses actions: ${scan.actions.join(', ')}`);
    }
    if (triggers.length > 0) {
      log.info(`declares agent triggers: ${triggers.join(', ')}`);
    }
  });

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
