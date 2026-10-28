/**
 * agent-app view <project-dir> [screen] [--width N] [--list]
 *
 * Print an app screen as text, exactly as the terminal edition lays it out:
 * the app's declared views.json, or the views generated from its operations
 * when it declares none. Read ops run against the RUNNING app. With --list,
 * print the screens and their actions instead.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { log } from '../lib/log.ts';
import { loadOps, loadProject, request, type ProjectRef } from '../lib/project.ts';
import {
  generateViews,
  renderBlock,
  requiredParams,
  toText,
  validateViews,
  type Operation,
  type Screen,
  type ViewsFile,
} from '../../../view/src/index.ts';

function loadViews(project: ProjectRef, ops: Operation[]): { views: ViewsFile; declared: boolean } {
  const path = join(project.dir, 'views.json');
  if (!existsSync(path)) return { views: generateViews(ops), declared: false };
  const raw = JSON.parse(readFileSync(path, 'utf8')) as unknown;
  const problems = validateViews(raw, ops);
  if (problems.length > 0) {
    throw new Error(`views.json is invalid:\n${problems.map(p => `  ${p.where}: ${p.message}`).join('\n')}`);
  }
  return { views: raw as ViewsFile, declared: true };
}

async function runRead(project: ProjectRef, op: Operation, params: Record<string, string>): Promise<unknown> {
  const exec = op.executor;
  let path = exec.type === 'crud' ? `/api/collections/${exec.collection ?? ''}/records` : (exec.path ?? '');
  const qs = new URLSearchParams(params).toString();
  if (qs) path += (path.includes('?') ? '&' : '?') + qs;
  const res = await request(project, 'GET', path);
  if (res.status < 200 || res.status >= 300) throw new Error(`${op.name}: HTTP ${res.status} ${res.body.slice(0, 200)}`);
  try {
    return JSON.parse(res.body) as unknown;
  } catch {
    return res.body;
  }
}

export async function renderScreen(project: ProjectRef, ops: Operation[], screen: Screen, width: number): Promise<string> {
  const byName = new Map(ops.map(op => [op.name, op]));
  const cache = new Map<string, unknown>();
  const out: string[] = [screen.title, '-'.repeat(Math.min(width, screen.title.length + 4))];
  for (const block of screen.blocks) {
    const ref = block.source ?? screen.source;
    let data: unknown = undefined;
    if (ref !== undefined) {
      const op = byName.get(ref.op);
      if (op === undefined) {
        out.push(`(unknown op ${ref.op})`);
        continue;
      }
      const params = Object.fromEntries(Object.entries(ref.params ?? {}).map(([k, v]) => [k, String(v)]));
      const missing = requiredParams(op).filter(p => !(p in params));
      if (missing.length > 0) {
        out.push(`(${op.name} needs ${missing.join(', ')})`);
        continue;
      }
      const key = `${op.name}?${JSON.stringify(params)}`;
      if (!cache.has(key)) cache.set(key, await runRead(project, op, params));
      data = cache.get(key);
    }
    out.push(toText(renderBlock(block, data, { width, maxRows: 15 }).lines), '');
  }
  if (screen.actions?.length) {
    out.push(screen.actions.map(a => `${a.key} ${a.label ?? a.op}`).join('   '));
  }
  return out.join('\n').trimEnd();
}

export async function run(args: string[]): Promise<number> {
  const widthIdx = args.indexOf('--width');
  const width = widthIdx !== -1 ? Number(args[widthIdx + 1]) : 100;
  const positional = args.filter((a, i) => !a.startsWith('--') && (i === 0 || args[i - 1] !== '--width'));
  const [dirArg, screenId] = positional;
  if (dirArg === undefined || !Number.isFinite(width) || width < 30) {
    log.error('Usage: agent-app view <project-dir> [screen] [--width N] [--list]');
    return 1;
  }
  const project = loadProject(dirArg);
  const ops = loadOps(project) as Operation[];
  const { views, declared } = loadViews(project, ops);

  if (args.includes('--list') || views.screens.length === 0) {
    log.raw(`${project.name}: ${declared ? 'declared views.json' : 'views generated from operations.json'}\n`);
    for (const s of views.screens) {
      const actions = (s.actions ?? []).map(a => `${a.key}=${a.op}`).join(' ');
      log.raw(`  ${s.id.padEnd(24)} ${s.title}${actions ? `   [${actions}]` : ''}`);
    }
    log.raw(`\nShow one:  agent-app view ${dirArg} <screen> [--width N]`);
    return 0;
  }

  const target = screenId ?? views.home ?? views.screens[0]?.id;
  const screen = views.screens.find(s => s.id === target);
  if (screen === undefined) {
    log.error(`No screen "${target}". Screens: ${views.screens.map(s => s.id).join(', ')}`);
    return 1;
  }
  log.raw(await renderScreen(project, ops, screen, width));
  return 0;
}
