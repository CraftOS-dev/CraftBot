import { expect, test, type Page } from '@playwright/test'

const requests = (page: Page, type: string) => page.evaluate(type => (window as any).panelRequests.filter((r: any) => r.type === type), type)
const session = {
  id: 'builder', type: 'agent_app', title: 'Quick Checklist', createdAt: '2026-11-10', lastActiveAt: '2026-11-10',
  agentAppFrameworkPending: true,
  agentAppBuild: { building: true, todos: [{ id: 'build', content: 'Build checklist', active_form: 'Building the checklist', status: 'in_progress' }] },
}
const app = { id: 'checklist', name: session.title, path: '/apps/checklist', status: 'stopped' }

test('creation keeps the original construction screen and its side chat until the live app is ready', async ({ page }, info) => {
  await page.setViewportSize({ width: 1500, height: 900 })
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await page.getByRole('button', { name: 'Add Agent App', exact: true }).click()
  await page.getByRole('button', { name: 'Create Custom', exact: true }).click()
  await page.getByPlaceholder('e.g., World News Dashboard', { exact: true }).fill(session.title)
  await page.getByRole('dialog').getByRole('textbox').last().fill('A checklist')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect.poll(async () => (await requests(page, 'agent_app_framework_request')).filter(r => r.operation === 'workflow').length).toBe(1)
  const workflow = (await requests(page, 'agent_app_framework_request')).find(r => r.operation === 'workflow')
  await page.evaluate(({ session, requestId }) => {
    const f = window as any
    f.panelReceive({ type: 'session_created', data: { session } })
    f.panelReceive({ type: 'chat_history', data: { sessionId: 'builder', messages: [{ messageId: 'builder-message', sender: 'CraftBot', style: 'agent', content: 'I am building your checklist.', timestamp: 1 }], hasMore: false } })
    f.panelReceive({ type: 'agent_app_framework_response', data: { requestId, status: 'success', result: { sessionId: 'builder', path: '/apps/checklist' } } })
  }, { session, requestId: workflow.requestId })

  const construction = page.getByText('Creating Quick Checklist', { exact: true })
  const composer = page.getByPlaceholder('Ask about this Agent App…')
  await expect(construction).toBeVisible()
  await expect(page.getByText('Building the checklist', { exact: true })).toBeVisible()
  await expect(page.getByText('I am building your checklist.', { exact: true })).toBeVisible()
  await expect(composer).toBeVisible()
  await expect(page.locator('[class*="dockMascot"]')).toBeVisible()
  const dockBounds = await construction.boundingBox()
  const chatBounds = await composer.boundingBox()
  expect(dockBounds!.x + dockBounds!.width).toBeLessThan(chatBounds!.x)
  await page.screenshot({ path: info.outputPath('creation-desktop.png') })
  await composer.fill('Make the checkboxes orange')
  await composer.press('Enter')
  await expect.poll(async () => (await requests(page, 'message')).at(-1)?.sessionId).toBe('builder')
  expect((await requests(page, 'message')).some(r => r.sessionId === 'main')).toBe(false)

  const registered = { ...session, agentAppFrameworkPending: false, agentAppFrameworkKey: JSON.stringify(['home', app.path, app.id]) }
  await page.evaluate(({ registered, app }) => {
    const f = window as any
    f.panelReceive({ type: 'session_updated', data: { session: registered } })
    f.panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [app], connected: [] } } })
    f.panelReceive({ type: 'session_busy', data: { sessionId: 'builder', busy: false } })
    f.panelReceive({ type: 'agent_app_todos', data: { projectId: 'framework-build:builder', todos: [{ id: 'verify', active_form: 'Verifying the checklist', status: 'in_progress' }] } })
  }, { registered, app })
  await expect(construction).toBeVisible()
  await expect(page.getByText('Verifying the checklist', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open Quick Checklist', exact: true })).toHaveClass(/agentAppTabActive/)
  expect(await requests(page, 'agent_app_framework_open')).toHaveLength(0)

  // Reopening the registered row still uses its builder, including a draft.
  await page.getByRole('button', { name: 'Back to chat', exact: true }).click()
  await page.getByRole('button', { name: 'Open Quick Checklist', exact: true }).click()
  await expect.poll(async () => (await requests(page, 'agent_app_framework_request')).filter(r => r.operation === 'attach').length).toBe(1)
  const attach = (await requests(page, 'agent_app_framework_request')).find(r => r.operation === 'attach')
  await page.evaluate(({ requestId, app }) => (window as any).panelReceive({ type: 'agent_app_framework_response', data: {
    requestId, status: 'success', result: { key: 'attachment', path: app.path, appId: app.id, sessionId: 'builder' },
  } }), { requestId: attach.requestId, app })
  await expect(construction).toBeVisible()
  await composer.fill('Keep this draft through launch')
  await page.evaluate(({ registered, app }) => {
    const f = window as any
    f.panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [{ ...app, status: 'running' }], connected: [] } } })
    f.panelReceive({ type: 'session_updated', data: { session: { ...registered, agentAppBuild: null } } })
  }, { registered, app })
  await expect(construction).toHaveCount(0)
  await expect.poll(async () => (await requests(page, 'agent_app_framework_open')).at(-1)?.appId).toBe('checklist')
  const open = (await requests(page, 'agent_app_framework_open')).at(-1)
  await page.evaluate(({ requestId, app }) => (window as any).panelReceive({ type: 'agent_app_framework_open', data: {
    requestId, status: 'success', data: { ...app, url: 'http://localhost:7935/tests/fixtures/panel-app.html' },
  } }), { requestId: open.requestId, app })
  await expect(page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' })).toBeVisible()
  await expect(composer).toHaveValue('Keep this draft through launch')
  await expect(page.getByText('I am building your checklist.', { exact: true })).toBeVisible()
})

test('reconnecting to a build on mobile restores progress above the app chat', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/tests/panel-agent-apps.html?mobile-layout&route=/session/builder')
  await expect(page.getByRole('button', { name: 'Back to chat', exact: true })).toBeVisible()
  await page.evaluate(({ session, app }) => {
    const f = window as any
    f.panelReceive({ type: 'session_list', data: { sessions: [{ ...session, agentAppFrameworkPending: false, agentAppFrameworkKey: JSON.stringify(['home', app.path, app.id]) }] } })
    f.panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [app], connected: [] } } })
  }, { session, app })
  const construction = page.getByText('Creating Quick Checklist', { exact: true })
  const composer = page.getByPlaceholder('Ask about this Agent App…')
  await expect(construction).toBeVisible()
  await expect(page.getByText('Building the checklist', { exact: true })).toBeVisible()
  await expect(composer).toBeInViewport()
  await expect(page.locator('[class*="dockMascot"]')).toBeInViewport()
  const dock = await construction.boundingBox(), chat = await composer.boundingBox()
  expect(dock!.y + dock!.height).toBeLessThan(chat!.y)
  expect(chat!.x).toBeGreaterThanOrEqual(0)
  expect(chat!.x + chat!.width).toBeLessThanOrEqual(390)
  expect(chat!.y + chat!.height).toBeLessThanOrEqual(844)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: info.outputPath('creation-mobile.png') })
  expect(await requests(page, 'agent_app_framework_open')).toHaveLength(0)
})
