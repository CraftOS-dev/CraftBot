import { test, expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import { mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { createInterface } from 'node:readline'

test('a real imported Kanban app accepts embedded input and persists across host navigation and restart', async ({ page }, testInfo) => {
  test.skip(!process.env.CRAFTBOT_TEST_PYTHON, 'Set CRAFTBOT_TEST_PYTHON to a Python with CraftBot dependencies')
  test.setTimeout(240_000)
  page.setDefaultTimeout(20_000)
  const root = resolve(process.cwd(), '../../../..')
  const state = await mkdtemp(join(tmpdir(), 'craftbot-board-live-'))
  const child = spawn(process.env.CRAFTBOT_TEST_PYTHON!, [join(root, 'tests/fixtures/framework-settings-host.py'), state, '--board'], { cwd: root, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
  const exited = new Promise<void>(resolve => child.once('exit', () => resolve()))
  let stderr = ''
  child.stderr.on('data', chunk => { stderr += chunk.toString() })
  const host = await new Promise<{ url: string; token: string }>((resolve, reject) => {
    createInterface({ input: child.stdout }).on('line', line => { if (line.startsWith('{"url":')) resolve(JSON.parse(line)) })
    child.on('exit', code => reject(new Error(`Host exited ${code}: ${stderr}`)))
  })
  try {
    await page.goto('/tests/panel-agent-apps.html?permissions-menu')
    await page.waitForFunction(() => typeof (window as any).panelConnectFramework === 'function')
    await page.evaluate(({ url, token }) => (window as any).panelConnectFramework(url, token), host)
    await page.getByRole('button', { name: 'Open Kanban Board', exact: true }).click()
    await expect(page.locator('iframe[data-framework]')).toHaveCount(1, { timeout: 20_000 })
    const frame = page.frameLocator('iframe[data-framework]')
    await frame.getByRole('navigation', { name: 'Main', exact: true }).getByRole('button', { name: 'New card', exact: true }).click()
    await frame.getByRole('textbox', { name: 'Title', exact: true }).fill('Embedded persistence check')
    await frame.getByRole('textbox', { name: 'Description', exact: true }).fill('Created inside CraftBot, using a real imported package.')
    await frame.getByRole('button', { name: 'Create card', exact: true }).click()
    await expect(frame.getByRole('button', { name: 'KB-1 Embedded persistence check', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Other chat', exact: true }).click()
    await page.getByRole('button', { name: 'Open Kanban Board', exact: true }).click()
    await expect(frame.getByText('Created inside CraftBot, using a real imported package.', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Options: Kanban Board', exact: true }).click()
    await page.getByRole('button', { name: 'Stop Kanban Board', exact: true }).click()
    await expect(page.locator('iframe[data-framework]')).toHaveCount(0, { timeout: 30_000 })
    await page.getByRole('menu').getByRole('button', { name: 'Start Kanban Board', exact: true }).click()
    await expect(frame.getByRole('button', { name: 'KB-1 Embedded persistence check', exact: true })).toBeVisible({ timeout: 60_000 })
    await page.keyboard.press('Escape')
    await page.screenshot({ path: testInfo.outputPath('real-imported-board.png') })
  } finally {
    await fetch(host.url + '/shutdown', { method: 'POST', headers: { 'X-Test-Token': host.token }, signal: AbortSignal.timeout(20_000) })
    await exited
  }
})
