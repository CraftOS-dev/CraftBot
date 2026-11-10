import { openFrameworkSettings } from './helpers/framework-settings'
import { test, expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import { mkdtemp, readFile, writeFile, readdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { createInterface } from 'node:readline'

test('settings perform real backups, restores, repeated exports, sharing and removal', async ({ page, request }) => {
  test.skip(!process.env.CRAFTBOT_TEST_PYTHON, 'Set CRAFTBOT_TEST_PYTHON to a Python with CraftBot dependencies')
  test.setTimeout(240_000)
  const root = resolve(process.cwd(), '../../../..')
  const state = await mkdtemp(join(tmpdir(), 'craftbot-settings-live-'))
  const child = spawn(process.env.CRAFTBOT_TEST_PYTHON!, [join(root, 'tests/fixtures/framework-settings-host.py'), state], { cwd: root, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
  const exited = new Promise<void>(resolve => child.once('exit', () => resolve()))
  let stderr = ''
  child.stderr.on('data', chunk => { stderr += chunk.toString() })
  const ready = new Promise<{ url: string; token: string; path: string; stale: string }>((resolve, reject) => {
    createInterface({ input: child.stdout }).on('line', line => { if (line.startsWith('{"url":')) resolve(JSON.parse(line)) })
    child.on('exit', code => reject(new Error(`Host exited ${code}: ${stderr}`)))
  })
  const host = await ready
  try {
    await page.goto('/tests/panel-agent-apps.html?permissions-menu')
    await page.waitForFunction(() => typeof (window as any).panelConnectFramework === 'function')
    await page.evaluate(({ url, token }) => (window as any).panelConnectFramework(url, token), host)
    await openFrameworkSettings(page, 'Settings fixture')
    const card = page.getByRole('article', { name: 'Settings fixture settings', exact: true })
    await expect(card.getByRole('button', { name: 'Back up now', exact: true })).toBeEnabled()
    await card.getByRole('checkbox', { name: 'Clean logs on restart', exact: true }).click()
    await expect(card.getByRole('checkbox', { name: 'Clean logs on restart', exact: true })).toBeChecked()
    await card.getByRole('checkbox', { name: 'Auto-launch on startup', exact: true }).click()
    await expect(card.getByRole('checkbox', { name: 'Auto-launch on startup', exact: true })).toBeChecked()
    await card.getByRole('checkbox', { name: 'Scheduled backups', exact: true }).click()
    await expect(card.getByRole('checkbox', { name: 'Scheduled backups', exact: true })).toBeChecked()
    await card.getByRole('combobox', { name: 'Frequency', exact: true }).selectOption('6h')
    await expect(card.getByRole('combobox', { name: 'Frequency', exact: true })).toHaveValue('6h')
    await card.getByRole('spinbutton', { name: 'Backups to keep', exact: true }).fill('3')
    await expect(card.getByRole('spinbutton', { name: 'Backups to keep', exact: true })).toHaveValue('3')
    // Remount the settings to prove these are saved host preferences.
    await page.reload()
    await page.waitForFunction(() => typeof (window as any).panelConnectFramework === 'function')
    await page.evaluate(({ url, token }) => (window as any).panelConnectFramework(url, token), host)
    await openFrameworkSettings(page, 'Settings fixture')
    await expect(card.getByRole('checkbox', { name: 'Auto-launch on startup', exact: true })).toBeChecked()
    await expect(card.getByRole('checkbox', { name: 'Clean logs on restart', exact: true })).toBeChecked()
    await expect(card.getByRole('combobox', { name: 'Frequency', exact: true })).toHaveValue('6h')
    await expect(card.getByRole('spinbutton', { name: 'Backups to keep', exact: true })).toHaveValue('3')
    await card.getByRole('button', { name: 'Back up now', exact: true }).click()
    await expect(card.getByRole('status')).toHaveText('Backup created', { timeout: 60_000 })
    await expect(card.getByRole('button', { name: 'Restore this backup', exact: true })).toHaveCount(1)
    await writeFile(join(host.path, 'data/state.txt'), 'changed after backup')
    await card.getByRole('button', { name: 'Restore this backup', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Restore', exact: true }).click()
    await expect(card.getByRole('status')).toHaveText('Backup restored', { timeout: 60_000 })
    expect(await readFile(join(host.path, 'data/state.txt'), 'utf8')).toBe('original')
    for (let attempt = 0; attempt < 2; attempt++) {
      await card.getByRole('button', { name: 'Export project', exact: true }).click()
      await expect(card.getByRole('status')).toHaveText('Package exported', { timeout: 30_000 })
    }
    expect((await readdir(join(state, 'exports'))).filter(name => name.endsWith('.zip'))).toHaveLength(2)
    await card.getByRole('button', { name: 'Stop Settings fixture', exact: true }).click()
    await expect(card.getByRole('button', { name: 'Start Settings fixture', exact: true })).toBeEnabled({ timeout: 30_000 })
    const share = card.getByRole('region', { name: 'Share', exact: true })
    await share.getByRole('button', { name: 'Create LAN Link', exact: true }).click()
    await expect(share.locator('code')).toHaveCount(1, { timeout: 60_000 })
    let link = (await share.locator('code').innerText()).trim()
    let response = await request.get(link, { timeout: 20_000 })
    expect(response.ok(), await response.text()).toBeTruthy()
    expect(await response.text()).toContain('Disposable settings fixture')
    await card.getByRole('button', { name: 'Stop Settings fixture', exact: true }).click()
    await expect(share.locator('code')).toHaveCount(0, { timeout: 30_000 })
    if (process.env.CRAFTBOT_TEST_PUBLIC_TUNNEL === '1') {
      await share.getByRole('button', { name: 'Create Tunnel', exact: true }).click()
      await expect(share.locator('code')).toHaveCount(1, { timeout: 90_000 })
      link = (await share.locator('code').innerText()).trim()
      await expect(async () => {
        response = await request.get(link, { timeout: 20_000 })
        expect(response.ok(), await response.text()).toBeTruthy()
        expect(await response.text()).toContain('Disposable settings fixture')
      }).toPass({ timeout: 60_000 })
      await share.getByRole('button', { name: 'Stop', exact: true }).click()
      await expect(share.locator('code')).toHaveCount(0)
    }
    await card.getByRole('button', { name: 'Delete this backup', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(card.getByRole('button', { name: 'Restore this backup', exact: true })).toHaveCount(0)
    await page.getByRole('article', { name: 'Missing fixture settings' }).getByRole('button', { name: 'Delete Missing fixture', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('without deleting any files')
    await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(page.getByRole('article', { name: 'Missing fixture settings' })).toHaveCount(0)
    const unowned = page.getByRole('article', { name: 'Unowned fixture settings', exact: true })
    await unowned.getByRole('button', { name: 'Delete Unowned fixture', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('has not deleted any files')
    expect(await readFile(join(state, 'unowned-app/keep.txt'), 'utf8')).toBe('Keep this source and data.')
    await page.getByRole('dialog').getByRole('button', { name: 'Remove from list', exact: true }).click()
    await expect(unowned).toHaveCount(0)
    expect(await readFile(join(state, 'unowned-app/keep.txt'), 'utf8')).toBe('Keep this source and data.')
    await writeFile(join(host.path, 'data/state.txt'), 'latest before removal')
    await card.getByRole('button', { name: 'Delete Settings fixture', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(card).toHaveCount(0, { timeout: 30_000 })
    // A missing custom toolkit cannot make the most recent live data disappear.
    const archives = join(state, 'registry/removed')
    const contents: string[] = []
    for (const folder of await readdir(archives)) {
      const backups = join(archives, folder, 'backups')
      for (const backup of await readdir(backups)) contents.push(await readFile(join(backups, backup, 'state.txt'), 'utf8'))
    }
    expect(contents).toContain('latest before removal')
  } finally {
    await fetch(host.url + '/shutdown', { method: 'POST', headers: { 'X-Test-Token': host.token }, signal: AbortSignal.timeout(20_000) })
    await exited
  }
})
