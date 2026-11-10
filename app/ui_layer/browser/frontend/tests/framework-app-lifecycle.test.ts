import { openFrameworkSettings } from './helpers/framework-settings'
import { expect, test, type Page } from '@playwright/test'

const apps = [
  { id: 'notes', name: 'Framework notes', path: '/framework/notes', status: 'stopped' },
  { id: 'other', name: 'Other app', path: '/framework/other', status: 'running' },
  { id: 'missing', name: 'Missing app', path: '/framework/missing', status: 'missing' },
]
const registry = (page: Page) => page.getByRole('region', { name: 'Discovered apps', exact: true })
const view = (page: Page) => page.getByRole('region', { name: 'App view', exact: true })
const send = (page: Page, type: string, data: unknown) => page.evaluate(({ type, data }) => (window as any).panelReceive({ type, data }), { type, data })
const last = (page: Page, type = 'agent_app_framework_lifecycle') => page.evaluate(type => (window as any).panelRequests.filter((r: any) => r.type === type).at(-1), type)
const lifecycle = (page: Page, data: unknown) => send(page, 'agent_app_framework_lifecycle', data)
const list = (page: Page, status = 'stopped') => send(page, 'agent_app_framework_list', { status: 'success', data: {
  apps: [{ ...apps[0], status }, ...apps.slice(1)], connected: [{ appId: 'remote', name: 'Remote app', origin: 'https://example.test', status: 'online' }],
} })
async function open(page: Page) {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await expect(page.getByRole('button', { name: 'Collapse sidebar', exact: true })).toBeVisible()
  await list(page)
  await page.getByRole('button', { name: 'Show more (2)', exact: true }).click()
  await options(page, 'Framework notes')
}

async function options(page: Page, name: string) {
  const button = registry(page).getByRole('button', { name: `Options: ${name}`, exact: true })
  if (await button.getAttribute('aria-expanded') !== 'true') {
    const current = registry(page).getByRole('button', { name: /^Options:/, expanded: true })
    if (await current.count()) await current.click()
    await button.click()
  }
}

test('Start and Stop use observed statuses, disable duplicates, and leave legacy projects alone', async ({ page }, testInfo) => {
  await open(page)
  const start = page.getByRole('button', { name: 'Start Framework notes', exact: true })
  await start.click()
  await expect(start).toBeDisabled()
  await expect(start).toContainText('Starting…')
  await expect(registry(page).getByRole('button', { name: 'Open Framework notes', exact: true })).toHaveAttribute('title', /Stopped/)
  const req = await last(page)
  expect(req.operation).toBe('start')
  expect(req.appId).toBe('notes')
  expect(req.path).toBe('/framework/notes')
  await list(page, 'running')
  await expect(start).toBeDisabled()
  await lifecycle(page, { ...req, status: 'success' })
  const stop = page.getByRole('button', { name: 'Stop Framework notes', exact: true })
  await expect(stop).toBeEnabled()
  await page.screenshot({ path: testInfo.outputPath('registry-start-stop.png') })
  await stop.click()
  const stopping = await last(page)
  expect(stopping.operation).toBe('stop')
  await expect(stop).toContainText('Stopping…')
  await list(page)
  await lifecycle(page, { ...stopping, status: 'success', remaining: true })
  await expect(start).toBeEnabled()
  await expect(registry(page).getByText('A development instance or task bridge is still running.')).toBeVisible()
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) => ['agent_app_launch', 'agent_app_stop', 'agent_app_delete'].includes(r.type)))).toEqual([])
  expect(await page.evaluate(() => (window as any).panelStore.getState().agentApp.projects.map((p: any) => p.name))).toEqual(['Notes', 'Calendar', 'Weather'])
})

test('command errors keep actual state and remain visible without Advanced', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Start Framework notes', exact: true }).click()
  const req = await last(page)
  await list(page)
  await lifecycle(page, { ...req, status: 'error', code: 'command_failed', message: 'Agent-App could not complete the command.', stderr: 'system-managed files changed outside tooling' })
  await expect(registry(page).getByRole('alert')).toHaveText('Agent-App could not complete the command.')
  await expect(registry(page).getByText('Agent-App details', { exact: true })).toHaveCount(0)
  await openFrameworkSettings(page, 'Framework notes')
  const card = page.getByRole('article', { name: 'Framework notes settings' })
  await expect(card.getByRole('button', { name: 'Advanced', exact: true })).toHaveCount(0)
  await expect(card.getByRole('alert')).toHaveText('Agent-App could not complete the command.')
  await page.getByRole('button', { name: 'Back to chat', exact: true }).click()
  await options(page, 'Framework notes')
  await expect(page.getByRole('button', { name: 'Start Framework notes', exact: true })).toBeEnabled()
  await options(page, 'Other app')
  await expect(page.getByRole('button', { name: 'Stop Other app', exact: true })).toBeEnabled()
})

test('a stale completion cannot settle a newer command', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Start Framework notes', exact: true }).click()
  const first = await last(page)
  await list(page, 'running')
  await lifecycle(page, { ...first, status: 'success' })
  const stop = page.getByRole('button', { name: 'Stop Framework notes', exact: true })
  await stop.click()
  await lifecycle(page, { ...first, status: 'success' })
  await expect(stop).toContainText('Stopping…')
  await expect(stop).toBeDisabled()
})

test('missing and remote apps have no lifecycle controls; stale lists disable the others', async ({ page }) => {
  await open(page)
  await options(page, 'Missing app')
  await expect(page.getByRole('button', { name: /^(Start|Stop) (Missing app|Remote app)$/ })).toHaveCount(0)
  await options(page, 'Framework notes')
  await send(page, 'agent_app_framework_list', { status: 'error', message: 'query failed' })
  await expect(page.getByRole('button', { name: 'Start Framework notes', exact: true })).toBeDisabled()
  await options(page, 'Other app')
  await expect(page.getByRole('button', { name: 'Stop Other app', exact: true })).toBeDisabled()
})

test('disconnect never replays Start and a reconnect can join the running command', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Start Framework notes', exact: true }).click()
  const req = await last(page)
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: false }))
  await expect(registry(page).getByText(/Connection interrupted/)).toBeVisible()
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: true }))
  await lifecycle(page, { ...req, status: 'running' })
  await list(page)
  await expect(page.getByRole('button', { name: 'Start Framework notes', exact: true })).toBeDisabled()
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_lifecycle').length)).toBe(1)
  await list(page, 'running')
  await lifecycle(page, { ...req, status: 'success' })
  await expect(page.getByRole('button', { name: 'Stop Framework notes', exact: true })).toBeEnabled()
})

test('joining another tab makes clear that a second command was not queued', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Start Framework notes', exact: true }).click()
  const req = await last(page)
  await lifecycle(page, { ...req, requestId: 'other-tab', status: 'running', message: 'An operation is already in progress. Wait for it to finish before sending another command.' })
  await expect(registry(page).getByText(/An operation is already in progress/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start Framework notes', exact: true })).toBeDisabled()
  await list(page, 'running')
  await lifecycle(page, { ...req, requestId: 'other-tab', status: 'success' })
  await expect(registry(page).getByText(/An operation is already in progress/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Stop Framework notes', exact: true })).toBeEnabled()
})

test('the app view starts a stopped app and closes its frame when Stop begins', async ({ page }, testInfo) => {
  await open(page)
  await page.getByRole('button', { name: 'Open Framework notes', exact: true }).click()
  await expect.poll(async () => (await last(page, 'agent_app_framework_open'))?.appId).toBe('notes')
  const openReq = await last(page, 'agent_app_framework_open')
  await send(page, 'agent_app_framework_open', { requestId: openReq.requestId, status: 'error', code: 'stopped', message: 'Stopped' })
  await view(page).getByRole('button', { name: 'Start Framework notes', exact: true }).click()
  const startReq = await last(page)
  await list(page, 'running')
  await lifecycle(page, { ...startReq, status: 'success' })
  await expect.poll(async () => (await last(page, 'agent_app_framework_open'))?.requestId).not.toBe(openReq.requestId)
  const verified = await last(page, 'agent_app_framework_open')
  const result = { requestId: verified.requestId, status: 'success', data: { ...apps[0], url: 'http://localhost:7935/tests/fixtures/panel-app.html' } }
  await send(page, 'agent_app_framework_open', result)
  await expect(page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' })).toBeVisible()
  await view(page).screenshot({ path: testInfo.outputPath('app-view-stop.png') })
  await options(page, 'Framework notes')
  await page.getByRole('button', { name: 'Stop Framework notes', exact: true }).click()
  await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
  await send(page, 'agent_app_framework_open', result)
  await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
  const stopReq = await last(page)
  await list(page)
  await lifecycle(page, { ...stopReq, status: 'success' })
  await expect(view(page).getByRole('button', { name: 'Start Framework notes', exact: true })).toBeEnabled()
})

test('collapsed flyout can start an app without opening or closing it', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click()
  await page.getByRole('button', { name: 'Agent App', exact: true }).click()
  await options(page, 'Framework notes')
  await page.getByRole('button', { name: 'Start Framework notes', exact: true }).click()
  await expect(registry(page)).toBeVisible()
  await expect(view(page)).toHaveCount(0)
  expect((await last(page)).operation).toBe('start')
})

test('socket sendNow never queues a disconnected or failed mutation', async ({ page }) => {
  await open(page)
  const outcome = await page.evaluate(async () => {
    const { SocketClient } = await import('/src/store/socket/SocketClient.ts')
    const client = new SocketClient({ url: 'ws://unused.test' }) as any
    const request = { operation: 'start' }
    const disconnected = client.sendNow('agent_app_framework_lifecycle', request)
    const sent: string[] = []
    client.ws = { readyState: WebSocket.OPEN, send: (value: string) => sent.push(value) }
    const connected = client.sendNow('agent_app_framework_lifecycle', request)
    client.ws.send = () => { throw new Error('connection lost') }
    const failed = client.sendNow('agent_app_framework_lifecycle', request)
    return { disconnected, connected, failed, queued: client.outbox.length, sent: sent.map(value => JSON.parse(value)) }
  })
  expect(outcome).toEqual({ disconnected: false, connected: true, failed: false, queued: 0, sent: [{ type: 'agent_app_framework_lifecycle', operation: 'start' }] })
})
