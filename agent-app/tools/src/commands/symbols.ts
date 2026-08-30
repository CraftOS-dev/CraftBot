/**
 * lui symbols <file.ts|.tsx|.js> — exact symbol table for scoped walk-verify.
 *
 * Prints JSON: [{ name, start, end, depth, kind }] (1-based inclusive lines)
 * for every named declaration — functions, arrow-function consts, classes,
 * methods, interfaces/types, module constants — including NESTED ones (a
 * handler declared inside a React component). The host attributes diff
 * hunks to the innermost symbol; the heuristic Python parser is the fallback
 * when this command cannot run (no typescript resolvable, syntax error).
 *
 * Resolution order for `typescript`: the project's own frontend/node_modules
 * (exactly what Vite builds with) when the file lives under one, else the
 * workspace's. Never fails loudly — an empty array is the "no exact table"
 * answer and the caller falls back.
 */
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { log } from '../lib/log.ts';

interface Sym {
  name: string;
  start: number;
  end: number;
  depth: number;
  kind: string;
}

function findFrontendRoot(file: string): string | null {
  let dir = dirname(resolve(file));
  for (let i = 0; i < 12; i++) {
    if (existsSync(join(dir, 'node_modules', 'typescript'))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function loadTypescript(file: string): any | null {
  const candidates: string[] = [];
  const projectRoot = findFrontendRoot(file);
  if (projectRoot !== null) candidates.push(join(projectRoot, 'package.json'));
  candidates.push(import.meta.url);
  for (const from of candidates) {
    try {
      const req = createRequire(from);
      return req('typescript');
    } catch {
      // try the next resolution root
    }
  }
  return null;
}

export const summary = 'Print the symbol table of a TS/TSX/JS file as JSON (scoped verify attribution)';

export async function run(args: string[]): Promise<number> {
  const file = args[0];
  if (file === undefined || !existsSync(file)) {
    log.error('Usage: lui symbols <file.ts|.tsx|.js|.jsx>');
    return 1;
  }
  const ts = loadTypescript(file);
  if (ts === null) {
    // Not an error for the caller — it falls back to the heuristic parser.
    log.raw('[]');
    return 0;
  }
  const text = readFileSync(file, 'utf8');
  const scriptKind = file.endsWith('.tsx')
    ? ts.ScriptKind.TSX
    : file.endsWith('.jsx')
      ? ts.ScriptKind.JSX
      : file.endsWith('.js') || file.endsWith('.mjs') || file.endsWith('.cjs')
        ? ts.ScriptKind.JS
        : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, scriptKind);
  const out: Sym[] = [];

  const lineOf = (pos: number): number => sf.getLineAndCharacterOfPosition(pos).line + 1;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const push = (name: string, node: any, depth: number, kind: string): void => {
    out.push({
      name,
      start: lineOf(node.getStart(sf)),
      end: lineOf(node.getEnd()),
      depth,
      kind,
    });
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const isFnLike = (n: any): boolean =>
    ts.isArrowFunction(n) || ts.isFunctionExpression(n) || ts.isFunctionDeclaration(n);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const visit = (node: any, depth: number): void => {
    let nextDepth = depth;
    if (ts.isFunctionDeclaration(node) && node.name) {
      push(node.name.text, node, depth, 'fn');
      nextDepth = depth + 1;
    } else if (ts.isClassDeclaration(node) && node.name) {
      push(node.name.text, node, depth, 'class');
      nextDepth = depth + 1;
    } else if (
      (ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) || ts.isEnumDeclaration(node)) &&
      node.name
    ) {
      push(node.name.text, node, depth, 'type');
    } else if (ts.isMethodDeclaration(node) && node.name && ts.isIdentifier(node.name)) {
      push(node.name.text, node, depth, 'fn');
      nextDepth = depth + 1;
    } else if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
      const init = node.initializer;
      const kind = init !== undefined && isFnLike(init) ? 'fn' : 'const';
      // Range = the whole declaration (name → initializer end).
      push(node.name.text, node, depth, kind);
      if (kind === 'fn') nextDepth = depth + 1;
    }
    ts.forEachChild(node, (child: unknown) => visit(child, nextDepth));
  };
  visit(sf, 0);

  log.raw(JSON.stringify(out));
  return 0;
}
