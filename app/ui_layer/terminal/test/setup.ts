/**
 * The browser globals the shared store expects (src/platform/globals.ts),
 * installed before each test file as boot.ts does for the client. UI state
 * goes to a throwaway folder.
 */
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installBrowserGlobals } from '../src/platform/globals'

installBrowserGlobals(mkdtempSync(join(tmpdir(), 'craftbot-tui-test-')), 7925)
