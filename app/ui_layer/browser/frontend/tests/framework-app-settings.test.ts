import { openFrameworkSettings } from './helpers/framework-settings'
import { expect, test, type Page } from '@playwright/test'

const app = { id: 'notes', name: 'Registry notes', path: '/registry/notes', status: 'running' }
const calls = (page: Page, operation: string) => page.evaluate(operation => (window as any).panelRequests.filter((request: any) => request.type === 'agent_app_framework_request' && request.operation === operation && request.action !== 'info'), operation)
const reply = (page: Page, requestId: string, result: unknown) => page.evaluate(({ requestId, result }) => (window as any).panelReceive({ type: 'agent_app_framework_response', data: { requestId, status: 'success', result } }), { requestId, result })
async function setup(page: Page) {
  await page.setViewportSize({ width: 1440, height: 1080 })
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await expect(page.getByRole('button', { name: 'Collapse sidebar', exact: true })).toBeVisible()
  await page.evaluate(app => (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [app], connected: [] } } }), app)
  await openFrameworkSettings(page, 'Registry notes')
  const card = page.getByRole('article', { name: 'Registry notes settings' })
  await expect(card.getByRole('checkbox', { name: 'Auto-launch on startup' })).toBeEnabled()
  await expect.poll(async () => (await calls(page, 'details')).length).toBeGreaterThan(0)
  for (const request of await calls(page, 'details')) await reply(page, request.requestId, { capabilities: { declared: {} } })
  for (const request of await calls(page, 'maintenance')) await reply(page, request.requestId, { port: 8123, backups: [{ filename: '2026-11-09T12-00-00-000Z-1-0', ts: 1794225600000, trigger: 'manual', size: 1024 }], backupStatus: { count: 1, totalSize: 1024 }, links: {} })
  return card
}

test('settings keep the original sections without Advanced or developer controls', async ({ page }, info) => {
  const card = await setup(page)
  for (const name of ['Preferences', 'Requests', 'Backups', 'Share']) await expect(card.getByRole('region', { name, exact: true })).toBeVisible()
  await expect(card.getByRole('button', { name: 'View requests (0)', exact: true })).toHaveCount(0)
  await card.getByRole('button', { name: 'About app requests', exact: true }).click()
  await expect(card.getByText("Your requests use this app's existing CraftBot conversation.", { exact: false })).toBeVisible()
  await expect(card.getByText("Other users' requests stay in separate conversations.", { exact: false })).toBeVisible()
  await card.getByRole('button', { name: 'Hide requests', exact: true }).click()
  await expect(card.getByRole('button', { name: 'Export project', exact: true })).toBeVisible()
  await expect(card.getByRole('textbox', { name: 'Backup ID' })).toHaveCount(0)
  await expect(card.getByRole('region', { name: 'Advanced', exact: true })).toHaveCount(0)
  for (const name of ['Advanced', 'Open conversation', 'Validate', 'Verify independently', 'App capabilities']) {
    await expect(card.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  await card.screenshot({ path: info.outputPath('restored-settings-card.png') })
  await expect(card.getByRole('checkbox', { name: 'Clean logs on restart' })).toBeVisible()
  await expect(card.getByRole('checkbox', { name: 'Scheduled backups' })).toBeVisible()
  await expect(card.getByRole('button', { name: 'Create LAN Link', exact: true })).toBeVisible()
  await expect(card.getByRole('button', { name: 'Restore this backup', exact: true })).toBeVisible()
  expect(await calls(page, 'manage')).toEqual([])
})

test('shared card headers preserve legacy lifecycle and registry export routing', async ({ page }) => {
  const card = await setup(page)
  await page.getByRole('article', { name: 'Notes settings', exact: true }).getByRole('button', { name: 'Stop', exact: true }).click()
  expect(await page.evaluate(() => (window as any).panelRequests.filter((request: any) => request.type === 'agent_app_stop'))).toEqual([{ type: 'agent_app_stop', projectId: 'notes' }])
  await card.getByRole('button', { name: 'Export project', exact: true }).click()
  await expect.poll(async () => (await calls(page, 'manage')).length).toBe(1)
  await expect(card.getByRole('button', { name: 'Export project', exact: true })).toBeDisabled()
  const request = (await calls(page, 'manage'))[0]
  expect(request).toMatchObject({ verb: 'export', path: app.path, appId: app.id })
  await reply(page, request.requestId, { status: 'success', data: { ok: true, file: '/exports/notes.zip' } })
  await expect(card.getByRole('status')).toHaveText('Package exported')
  await expect(card.getByText('/exports/notes.zip', { exact: true })).toBeVisible()
  await expect(card.locator('pre')).toHaveCount(0)
})

test('request switches preserve scoped consent and failed backups show an inline error', async ({ page }) => {
  const card = await setup(page)
  const requestsToggle = card.getByRole('checkbox', { name: 'Allow requests to CraftBot', exact: true })
  const ownerToggle = card.getByRole('region', { name: 'Requests', exact: true }).getByRole('checkbox', { name: 'Owner access to local tools', exact: true })
  await expect(ownerToggle).toBeDisabled()
  await requestsToggle.click()
  await expect.poll(async () => (await calls(page, 'consent')).length).toBe(1)
  const first = (await calls(page, 'consent'))[0]
  expect(first).toMatchObject({ path: app.path, appId: app.id, allow: true, ownerTools: false })
  await reply(page, first.requestId, { path: app.path, appId: app.id, tasksAllowed: true, ownerToolsAllowed: false })
  await expect(requestsToggle).toBeChecked()
  await ownerToggle.click()
  await expect.poll(async () => (await calls(page, 'consent')).length).toBe(2)
  const second = (await calls(page, 'consent'))[1]
  expect(second).toMatchObject({ path: app.path, appId: app.id, allow: true, ownerTools: true })
  await reply(page, second.requestId, { path: app.path, appId: app.id, tasksAllowed: true, ownerToolsAllowed: true })
  await expect(ownerToggle).toBeChecked()
  await card.getByRole('button', { name: 'Back up now', exact: true }).click()
  await expect.poll(async () => (await calls(page, 'manage')).length).toBe(1)
  const backup = (await calls(page, 'manage'))[0]
  expect(backup).toMatchObject({ path: app.path, appId: app.id, verb: 'backup' })
  await reply(page, backup.requestId, { status: 'error', stderr: 'Backup storage unavailable.', data: { ok: false } })
  await expect(card.getByRole('alert')).toHaveText('Backup storage unavailable.')
  await expect(card.getByText('Backup created', { exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => (window as any).panelRequests.some((request: any) => request.type === 'agent_app_trigger_consent'))).toBe(false)
})

test('Kanban backup controls persist preferences and confirm the selected archive', async ({ page }) => {
  const card = await setup(page)
  await card.getByRole('checkbox', { name: 'Scheduled backups', exact: true }).click()
  await expect.poll(async () => (await calls(page, 'preference')).length).toBe(1)
  const preference = (await calls(page, 'preference'))[0]
  expect(preference).toMatchObject({ path: app.path, appId: app.id, backupsEnabled: true })
  await reply(page, preference.requestId, { path: app.path, appId: app.id, backupsEnabled: true, backupInterval: 'daily', backupKeep: 7 })
  await expect(card.getByRole('combobox', { name: 'Frequency' })).toHaveValue('daily')
  await card.getByRole('combobox', { name: 'Frequency' }).selectOption('6h')
  await expect.poll(async () => (await calls(page, 'preference')).length).toBe(2)
  const frequency = (await calls(page, 'preference'))[1]
  expect(frequency).toMatchObject({ backupInterval: '6h' })
  await reply(page, frequency.requestId, { path: app.path, appId: app.id, backupsEnabled: true, backupInterval: '6h', backupKeep: 7 })
  await card.getByRole('button', { name: 'Restore this backup', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  expect(await calls(page, 'manage')).toEqual([])
  await dialog.getByRole('button', { name: 'Restore', exact: true }).click()
  await expect.poll(async () => (await calls(page, 'manage')).length).toBe(1)
  expect((await calls(page, 'manage'))[0]).toMatchObject({ path: app.path, appId: app.id, verb: 'restore', backupId: '2026-11-09T12-00-00-000Z-1-0' })
})

test('Kanban share controls open and revoke the registry app link without legacy requests', async ({ page }) => {
  const card = await setup(page)
  await card.getByRole('button', { name: 'Create LAN Link', exact: true }).click()
  await expect.poll(async () => (await calls(page, 'sharing')).length).toBe(1)
  const open = (await calls(page, 'sharing'))[0]
  expect(open).toMatchObject({ path: app.path, appId: app.id, action: 'open', channel: 'lan' })
  await reply(page, open.requestId, { lan: 'http://192.0.2.1:8123/?a2app_share=fixture' })
  const share = card.getByRole('region', { name: 'Share', exact: true })
  await expect(share.getByText('http://192.0.2.1:8123/?a2app_share=fixture', { exact: true })).toBeVisible()
  await share.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect.poll(async () => (await calls(page, 'sharing')).length).toBe(2)
  const close = (await calls(page, 'sharing'))[1]
  expect(close).toMatchObject({ action: 'close', channel: 'lan', path: app.path, appId: app.id })
  await reply(page, close.requestId, {})
  await expect(share.getByRole('button', { name: 'Create LAN Link', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as any).panelRequests.some((request: any) => ['agent_app_share_open', 'agent_app_share_close'].includes(request.type)))).toBe(false)
})
