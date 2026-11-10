import { expect, test } from '@playwright/test'
import { spawn } from 'node:child_process'
import { mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'

test('real re-scaffolding preserves construction and history across app switches and reload', async ({ page }, info) => {
  test.skip(!process.env.CRAFTBOT_TEST_PYTHON, 'Set CRAFTBOT_TEST_PYTHON to a Python with CraftBot dependencies')
  test.setTimeout(120_000)
  const root = resolve(process.cwd(), '../../../..')
  const state = await mkdtemp(join(tmpdir(), 'craftbot-creation-live-'))
  const child = spawn(process.env.CRAFTBOT_TEST_PYTHON!, [join(root, 'tests/fixtures/framework-creation-host.py'), state], {
    cwd: root, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  })
  const exited = new Promise<void>(resolve => child.once('exit', () => resolve()))
  let stderr = ''
  child.stderr.on('data', chunk => { stderr += chunk.toString() })
  const host = await new Promise<{ url: string; token: string; sessionId: string }>((resolve, reject) => {
    createInterface({ input: child.stdout }).on('line', line => { if (line.startsWith('{"url":')) resolve(JSON.parse(line)) })
    child.on('exit', code => reject(new Error(`Host exited ${code}: ${stderr}`)))
  })
  try {
    const connect = async () => {
      await page.goto('/tests/panel-agent-apps.html?permissions-menu')
      await page.waitForFunction(() => typeof (window as any).panelConnectFramework === 'function')
      await page.evaluate(host => (window as any).panelConnectFramework(host.url, host.token), host)
    }
    await connect()
    await page.getByRole('button', { name: 'Open Todo list', exact: true }).click()
    const construction = page.getByText('Creating Todo list', { exact: true })
    const history = page.getByText('I am building your Todo list.', { exact: true })
    await expect(construction).toBeVisible()
    await expect(history).toBeVisible()
    await page.getByPlaceholder('Ask about this Agent App…').fill('Keep my Todo draft')
    const response = await fetch(host.url + '/rescaffold', { method: 'POST', headers: { 'X-Test-Token': host.token } })
    expect(response.ok).toBeTruthy()
    const result = await response.json()
    expect(result.secondId).not.toBe(result.firstId)
    expect(result.sessions).toBe(2) // Builder + Research; no replacement chat.

    for (let i = 0; i < 2; i++) {
      await page.getByRole('button', { name: 'Open Research Board', exact: true }).click()
      await expect(page.getByText('This is the Research Board conversation.', { exact: true })).toBeVisible()
      await expect(history).toHaveCount(0)
      await page.getByRole('button', { name: 'Open Todo list', exact: true }).click()
      await expect(construction).toBeVisible()
      await expect(history).toBeVisible()
      await expect(page.getByPlaceholder('Ask about this Agent App…')).toHaveValue('Keep my Todo draft')
      await expect(page.getByText('This app is stopped.', { exact: false })).toHaveCount(0)
    }
    await connect() // New browser store; history and build state come from the host.
    await page.getByRole('button', { name: 'Open Todo list', exact: true }).click()
    await expect(construction).toBeVisible()
    await expect(history).toBeVisible()
    await expect(page.locator('[class*="dockMascot"]')).toBeVisible()
    await page.screenshot({ path: info.outputPath('restored-todo-build.png') })
    const composer = page.getByPlaceholder('Ask about this Agent App…')
    await composer.fill('Continue building')
    await composer.press('Enter')
    await expect.poll(() => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'message').at(-1)?.sessionId)).toBe(host.sessionId)
  } finally {
    await fetch(host.url + '/shutdown', { method: 'POST', headers: { 'X-Test-Token': host.token } })
    await exited
  }
})
