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
  'adapter-sync': { summary: 'Re-vendor only the system pb_hooks (A2APP adapter) — no rebuild' },
};

/**
 * Errors must arrive TRUE or agents hallucinate around them. Node's fetch
 * throws a bare `TypeError: fetch failed` and hides the real reason
 * (ECONNREFUSED, ENOTFOUND, ETIMEDOUT…) in a nested `cause` /
 * AggregateError. Observed live: an agent read "✗ fetch failed" from a
 * connection-refused to its own STOPPED app and told the user "this
 * environment has NO outbound internet access; the code is 100% correct."
 * Unwrap the whole chain and, for connection failures to a local app, say
 * the one sentence that matters.
 */
function describeError(err: unknown): string {
  const parts: string[] = [];
  const seen = new Set<unknown>();
  let current: unknown = err;
  while (current !== undefined && current !== null && !seen.has(current)) {
    seen.add(current);
    if (current instanceof AggregateError) {
      for (const sub of current.errors) {
        const msg = sub instanceof Error ? sub.message : String(sub);
        if (msg) parts.push(msg);
      }
      current = undefined;
    } else if (current instanceof Error) {
      if (current.message) parts.push(current.message);
      current = (current as Error & { cause?: unknown }).cause;
    } else {
      parts.push(String(current));
      current = undefined;
    }
  }
  let message = parts.join(' — caused by: ');
  if (/ECONNREFUSED|ECONNRESET/.test(message)) {
    message +=
      '\nThe app is NOT RUNNING (connection refused is a dead local server, ' +
      'not a network problem). Relaunch it with living_ui_notify_ready, then retry.';
  } else if (/ENOTFOUND|EAI_AGAIN/.test(message)) {
    message += '\nDNS lookup failed for the target host — check the hostname.';
  } else if (/ETIMEDOUT|UND_ERR_CONNECT_TIMEOUT/.test(message)) {
    message += '\nThe target did not answer in time — it may be down or unreachable.';
  }
  return message || String(err);
}

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
  (code) => {
    // Set the exit code but let Node tear down its event loop naturally.
    // Calling process.exit() here races the async stdout pipe and libuv
    // threadpool handles (from fetch) on Windows, aborting with
    //   Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)  (async.c)
    // — which made even SUCCESSFUL commands (their JSON already flushed to
    // stdout) report a non-zero crash code, so run_shell marked them failed.
    // Undici unrefs idle sockets, so one-shot commands still exit promptly
    // once their request settles.
    process.exitCode = code;
  },
  (err: unknown) => {
    log.error(describeError(err));
    process.exitCode = 1;
  },
);
