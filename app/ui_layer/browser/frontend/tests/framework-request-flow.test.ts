import { test, expect, type Page } from '@playwright/test'

const requests = (page: Page, op: string) => page.evaluate(op => (window as any).panelRequests.filter((r: any) => r.operation === op), op)
const reply = (page: Page, requestId: string, result: unknown) => page.evaluate(({ requestId, result }) =>
  (window as any).panelReceive({ type: 'agent_app_framework_response', data: { requestId, status: 'success', result } }), { requestId, result })

async function setup(page: Page) {
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await expect(page.getByRole('button', { name: 'Collapse sidebar', exact: true })).toBeVisible()
  const app = { id: 'registry', name: 'Research Board', path: '/research', status: 'running' }
  await page.evaluate(app => (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [app], connected: [] } } }), app)
  await page.getByRole('button', { name: 'Open Research Board', exact: true }).click()
  await expect.poll(async () => (await requests(page, 'task_status')).length).toBeGreaterThan(0)
  const req = await page.evaluate(() => (window as any).panelRequests.find((r: any) => r.type === 'agent_app_framework_open'))
  await page.evaluate(({ req, app }) => (window as any).panelReceive({ type: 'agent_app_framework_open', data: { requestId: req.requestId, status: 'success', data: { ...app, url: 'http://localhost:7935/tests/fixtures/panel-app.html' } } }), { req, app })
  await page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' }).fill('Keep my draft')
  return (await requests(page, 'task_status')).at(-1)
}

test('registry request prompts for permission; Allow grants it without reloading the app', async ({ page }) => {
  const status = await setup(page)
  await reply(page, status.requestId, { permissionRequired: true, needsReview: true, revision: 'rev1', reviewId: 'request1', requests: ['reviews_waiting'] })
  const dialog = page.getByRole('dialog', { name: 'Agent App requesting access to CraftBot' })
  await expect(dialog).toBeVisible()
  expect(await requests(page, 'consent')).toHaveLength(0)
  await dialog.getByRole('button', { name: 'Allow', exact: true }).click()
  await expect.poll(async () => (await requests(page, 'consent')).length).toBe(1)
  const grant = (await requests(page, 'consent'))[0]
  expect(grant).toMatchObject({ path: '/research', appId: 'registry', allow: true, revision: 'rev1', reviewId: 'request1' })
  expect(grant.ownerTools).toBeUndefined()
  await reply(page, grant.requestId, { tasksAllowed: true })
  await expect(dialog).toHaveCount(0)
  await expect(page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' })).toHaveValue('Keep my draft')
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_open').length)).toBe(1)
})

test('declining stays declined and a failed delivery is visible beside the app', async ({ page }) => {
  const status = await setup(page)
  await reply(page, status.requestId, { permissionRequired: true, needsReview: true, revision: 'rev1', reviewId: 'request1', requests: ['reviews_waiting'] })
  await page.getByRole('dialog').getByRole('button', { name: "Don't allow", exact: true }).click()
  await expect.poll(async () => (await requests(page, 'consent')).length).toBe(1)
  const grant = (await requests(page, 'consent'))[0]
  expect(grant.allow).toBe(false)
  await reply(page, grant.requestId, { tasksAllowed: false })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Review requests' })).toBeVisible()
  await expect.poll(async () => (await requests(page, 'task_status')).length, { timeout: 10000 }).toBeGreaterThan(1)
  await reply(page, (await requests(page, 'task_status')).at(-1).requestId, { permissionRequired: false, needsReview: false, error: 'The app did not supply its task credential. Update or restart the app, then try again.' })
  await expect(page.getByRole('alert')).toContainText('did not supply its task credential')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' })).toHaveValue('Keep my draft')
})
