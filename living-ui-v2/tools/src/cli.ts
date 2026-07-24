#!/usr/bin/env node
/**
 * lui — Living UI workspace CLI.
 *
 * Thin dispatcher: each command is a module in ./commands exporting
 * { summary, run }. Composition over a framework (spec W4).
 */
import { log } from './lib/log.ts';

const COMMANDS: Record<string, { summary: string }> = {
  pb: { summary: 'Fetch/inspect the pinned PocketBase binary (cached per-OS)' },
  create: { summary: 'Scaffold a new Living UI project from the blueprint' },
  dev: { summary: 'Run a project in development mode (Vite + PocketBase)' },
  validate: { summary: 'Run the validation gate on a project' },
  verify: { summary: 'Headless smoke verification of a RUNNING project (mount, console, screenshot)' },
  ops: { summary: "List a project's declared operations (its agent-facing verbs)" },
  run: { summary: 'Execute a declared operation against the RUNNING app' },
  data: { summary: 'Read/write collection records of the RUNNING app (list/get/create/update/delete)' },
  probe: { summary: 'Scripted headless-browser walk of the RUNNING app (goto/click/type/read/screenshot)' },
  'kit-sync': { summary: 'Re-vendor the kit into a project (wholesale replace)' },
};

async function main(): Promise<number> {
  const [, , name, ...args] = process.argv;

  if (!name || name === 'help' || name === '--help') {
    log.raw('lui — Living UI workspace CLI\n');
    for (const [cmd, meta] of Object.entries(COMMANDS)) {
      log.raw(`  lui ${cmd.padEnd(10)} ${meta.summary}`);
    }
    return 0;
  }

  if (!(name in COMMANDS)) {
    log.error(`Unknown command: ${name}`);
    log.raw(`Try: lui help`);
    return 1;
  }

  const mod = (await import(`./commands/${name}.ts`)) as {
    run: (args: string[]) => Promise<number>;
  };
  return mod.run(args);
}

main().then(
  (code) => process.exit(code),
  (err: unknown) => {
    log.error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  },
);
