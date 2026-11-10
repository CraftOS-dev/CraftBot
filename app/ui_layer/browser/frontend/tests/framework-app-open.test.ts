import { expect, test, type Page } from '@playwright/test'

const apps = [
  { id: 'notes', name: 'Framework notes', path: '/framework/notes', status: 'running' },
  { id: 'other', name: 'Second app', path: '/framework/other', status: 'stopped' },
]
const view = (page: Page) => page.getByRole('region', { name: 'App view', exact: true })
const request = (page: Page) => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_open').at(-1))
const receive = (page: Page, data: unknown) => page.evaluate(data => (window as any).panelReceive({ type: 'agent_app_framework_open', data }), data)
const attachments = (page: Page) => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_request' && r.operation === 'attach'))
async function attachReply(page: Page, req: any, sessionId = 'notes-chat') {
  await page.evaluate(({ req, sessionId }) => (window as any).panelReceive({ type: 'agent_app_framework_response', data: {
    requestId: req.requestId, status: 'success', result: { key: req.path, path: req.path, appId: req.appId, sessionId },
  } }), { req, sessionId })
}

async function open(page: Page) {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await expect(page.getByRole('button', { name: 'Collapse sidebar', exact: true })).toBeVisible()
  await page.evaluate(apps => (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps, connected: [] } } }), apps)
}

async function select(page: Page, name = 'Framework notes') {
  await page.getByRole('button', { name: `Open ${name}`, exact: true }).click()
  await expect(view(page).getByText('Checking the app…', { exact: true })).toBeVisible()
  const path = name === 'Framework notes' ? apps[0].path : apps[1].path
  await expect.poll(async () => (await request(page))?.path).toBe(path)
  return request(page)
}

async function success(page: Page, req: any, url = 'http://localhost:7935/tests/fixtures/panel-app.html') {
  await receive(page, { requestId: req.requestId, status: 'success', data: {
    id: req.appId, path: req.path, name: apps.find(app => app.path === req.path)!.name, url,
  } })
}

test('opens only after verification, with no legacy actions, and survives a legacy list refresh', async ({ page }, testInfo) => {
  await open(page)
  const req = await select(page)
  await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
  await success(page, req)
  const frame = page.frameLocator('iframe[data-framework]')
  await frame.getByRole('textbox', { name: 'App note' }).fill('Framework draft')
  await expect(view(page).getByRole('heading')).toHaveCount(0)
  await expect(view(page).getByRole('button', { name: 'Stop Framework notes' })).toHaveCount(0)
  await expect(view(page).getByText('Conversation and app settings')).toHaveCount(0)
  const appBounds = await page.locator('iframe[data-framework]').boundingBox()
  const viewBounds = await view(page).boundingBox()
  expect(Math.abs(appBounds!.y - viewBounds!.y)).toBeLessThanOrEqual(1)
  await expect(page.locator('iframe[data-framework]')).toHaveAttribute('allow', /microphone; camera/)
  const boot = await frame.locator('body').evaluate(() => (window as any).fixtureBoot)
  await page.evaluate(() => {
    const f = window as any
    f.panelReceive({ type: 'agent_app_list', data: { success: true, projects: f.panelProjects } })
  })
  await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Framework draft')
  expect(await frame.locator('body').evaluate(() => (window as any).fixtureBoot)).toBe(boot)
  await expect(frame.locator('#theme')).toHaveText('Waiting for theme')
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) =>
    ['agent_app_launch', 'agent_app_stop', 'agent_app_delete', 'agent_app_active', 'agent_app_trigger_consent'].includes(r.type)))).toEqual([])
  expect(await page.evaluate(() => (window as any).panelStore.getState().agentApp.projects.map((p: any) => p.name))).toEqual(['Notes', 'Calendar', 'Weather'])
  await view(page).screenshot({ path: testInfo.outputPath('framework-app-open.png') })
})

for (const [code, message] of [
  ['stopped', 'This app is stopped.'], ['missing', "This app's folder is missing."],
  ['unreachable', 'The app is unavailable'], ['identity_changed', 'The app at this location has changed.'],
  ['not_registered', 'This app is no longer registered at this location.'], ['separate_view', 'This app has a separate interface address'],
]) test(`${code} never loads a stale URL and can retry`, async ({ page }) => {
  await open(page)
  const req = await select(page)
  await receive(page, { requestId: req.requestId, status: 'error', code, message: 'Diagnostic' })
  await expect(view(page).getByRole('alert')).toContainText(message)
  await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
  await view(page).getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(async () => (await request(page))?.requestId).not.toBe(req.requestId)
  await success(page, await request(page))
  await expect(page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' })).toBeVisible()
})

test('out-of-order replies cannot open the previous app or a replacement identity', async ({ page }) => {
  await open(page)
  const first = await select(page)
  const second = await select(page, 'Second app')
  await success(page, first)
  await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
  await receive(page, { requestId: second.requestId, status: 'success', data: { id: 'wrong-id', path: second.path, name: 'Wrong app', url: 'http://localhost:7935/tests/fixtures/panel-app.html' } })
  await expect(view(page).getByRole('alert')).toContainText('The app at this location has changed.')
  await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
})

test('reconnect verifies again without reloading an unchanged view or losing edits', async ({ page }) => {
  await open(page)
  const first = await select(page)
  await success(page, first)
  const frame = page.frameLocator('iframe[data-framework]')
  await frame.getByRole('textbox', { name: 'App note' }).fill('Keep this edit')
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: false }))
  await expect(view(page).getByText('Connection lost. App status may be out of date.', { exact: true })).toBeVisible()
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: true }))
  await expect.poll(async () => (await request(page))?.requestId).not.toBe(first.requestId)
  await receive(page, { requestId: first.requestId, status: 'error', code: 'stopped', message: 'Old reply' })
  await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Keep this edit')
  await success(page, await request(page))
  await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Keep this edit')
})

test('a disconnected selection waits for the connection before resolving', async ({ page }) => {
  await open(page)
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: false }))
  await page.getByRole('button', { name: 'Open Framework notes', exact: true }).click()
  await expect(view(page).getByText('Connection lost. App status may be out of date.', { exact: true })).toBeVisible()
  expect(await request(page)).toBeUndefined()
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: true }))
  await expect.poll(async () => (await request(page))?.appId).toBe('notes')
})

for (const url of ['javascript:alert(1)', 'http://127.0.0.1:7935/tests/fixtures/panel-app.html', 'https://example.test']) {
  test(`does not embed an unsafe or same-origin address: ${url}`, async ({ page }) => {
    await open(page)
    await success(page, await select(page), url)
    await expect(view(page).getByRole('alert')).toContainText('The app is unavailable')
    await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
  })
}

test('collapsed flyout opens the framework view and closes itself', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click()
  await page.getByRole('button', { name: 'Agent App', exact: true }).click()
  await select(page)
  await expect(page.getByRole('menu')).toHaveCount(0)
  await success(page, await request(page))
  await expect(page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' })).toBeVisible()
})

test('a lost response times out and a late success cannot navigate the view', async ({ page }) => {
  await page.clock.install()
  await open(page)
  const req = await select(page)
  await page.clock.fastForward(51_000)
  await expect(view(page).getByRole('alert')).toContainText("Couldn't check this app.")
  await success(page, req)
  await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
  await view(page).getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(async () => (await request(page))?.requestId).not.toBe(req.requestId)
  await success(page, await request(page))
  await expect(page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' })).toBeVisible()
})

test('a stalled frame can retry only after a fresh verification', async ({ page }) => {
  await page.clock.install()
  let attempts = 0
  await page.route('http://localhost:7935/tests/fixtures/panel-app.html', route => {
    if (++attempts > 1) return route.continue()
    // Keep the first navigation pending until retry removes its frame.
  })
  await open(page)
  const req = await select(page)
  await success(page, req)
  await expect(view(page).getByText('Loading the app view…', { exact: true })).toBeVisible()
  await page.clock.fastForward(21_000)
  await expect(view(page).getByText(/hasn't finished loading/)).toBeVisible()
  await expect(page.locator('iframe[data-framework]')).toHaveCSS('visibility', 'hidden')
  await view(page).getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(async () => (await request(page))?.requestId).not.toBe(req.requestId)
  await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
  await success(page, await request(page))
  await expect(page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' })).toBeVisible()
})

test('registry apps reuse the Kanban chat split and preserve the frame and draft while resizing and toggling', async ({ page }) => {
  await open(page)
  await success(page, await select(page))
  await expect.poll(async () => (await attachments(page)).length).toBe(1)
  await attachReply(page, (await attachments(page))[0])
  const composer = page.getByPlaceholder('Ask about this Agent App…')
  await expect(composer).toBeVisible()
  const frame = page.frameLocator('iframe[data-framework]')
  await frame.getByRole('textbox', { name: 'App note' }).fill('Unsaved app state')
  const boot = await frame.locator('body').evaluate(() => (window as any).fixtureBoot)
  await composer.fill('Unsaved chat draft')
  const seam = page.getByRole('button', { name: 'Hide Chat', exact: true })
  const bounds = (await seam.boundingBox())!
  await page.mouse.move(bounds.x, bounds.y + bounds.height / 2)
  await page.mouse.down()
  await page.mouse.move(bounds.x - 70, bounds.y + bounds.height / 2, { steps: 10 })
  await page.mouse.up()
  await expect.poll(async () => (await seam.boundingBox())!.x).toBeLessThan(bounds.x - 50)
  await seam.press('Enter')
  await expect(composer).not.toBeInViewport()
  await page.getByRole('button', { name: 'Show Chat', exact: true }).press('Enter')
  await expect(composer).toHaveValue('Unsaved chat draft')
  await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Unsaved app state')
  expect(await frame.locator('body').evaluate(() => (window as any).fixtureBoot)).toBe(boot)
  expect((await attachments(page)).length).toBe(1)
  // Layout preferences are shared with the existing Kanban/legacy page.
  const width = await composer.locator('xpath=ancestor::div[contains(@class,"chatPanel_")]').evaluate(node => (node as HTMLElement).style.width)
  await page.getByRole('button', { name: 'Notes app page', exact: true }).click()
  await expect(composer).toHaveValue('Unsaved chat draft')
  const legacyWidth = await composer.locator('xpath=ancestor::div[contains(@class,"chatPanel_")]').evaluate(node => (node as HTMLElement).style.width)
  expect(legacyWidth).toBe(width)
  await composer.fill('Show the app status')
  await composer.press('Enter')
  await expect.poll(() => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'message').at(-1)?.sessionId)).toBe('notes-chat')
})

test('chat attaches only while connected and ignores a late reply for the previous app', async ({ page }) => {
  await open(page)
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: false }))
  await page.getByRole('button', { name: 'Open Framework notes', exact: true }).click()
  expect(await attachments(page)).toEqual([])
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: true }))
  await expect.poll(async () => (await attachments(page)).length).toBe(1)
  const first = (await attachments(page))[0]
  await select(page, 'Second app')
  await expect.poll(async () => (await attachments(page)).length).toBe(2)
  await attachReply(page, first)
  await expect(page.getByPlaceholder('Ask about this Agent App…')).toHaveCount(0)
  await attachReply(page, (await attachments(page))[1], 'other')
  const composer = page.getByPlaceholder('Ask about this Agent App…')
  await composer.fill('Second app request')
  await composer.press('Enter')
  await expect.poll(() => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'message').at(-1)?.sessionId)).toBe('other')
})

test('switching apps and chats reuses the verified frame and conversation without checking again', async ({ page }) => {
  await open(page)
  await success(page, await select(page))
  await expect.poll(async () => (await attachments(page)).length).toBe(1)
  await attachReply(page, (await attachments(page))[0])
  const frame = page.frameLocator('iframe[data-framework]')
  const composer = page.getByPlaceholder('Ask about this Agent App…')
  await frame.getByRole('textbox', { name: 'App note' }).fill('Keep my app state')
  await composer.fill('Keep my side chat draft')
  const boot = await frame.locator('body').evaluate(() => (window as any).fixtureBoot)
  const second = await select(page, 'Second app')
  await receive(page, { requestId: second.requestId, status: 'error', code: 'stopped', message: '' })
  await expect.poll(async () => (await attachments(page)).length).toBe(2)
  await attachReply(page, (await attachments(page))[1], 'other')
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: 'Open Framework notes', exact: true }).click()
    await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Keep my app state')
    await expect(composer).toHaveValue('Keep my side chat draft')
    await expect(view(page).getByText('Checking the app…', { exact: true })).toHaveCount(0)
    await expect(view(page).getByText('Loading the app view…', { exact: true })).toHaveCount(0)
    await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'loading' } }))
    await expect(page.getByText('Checking for apps…', { exact: true })).toHaveCount(0)
    expect(await frame.locator('body').evaluate(() => (window as any).fixtureBoot)).toBe(boot)
    await page.getByRole('button', { name: 'Other chat', exact: true }).click()
  }
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_open' && r.appId === 'notes').length)).toBe(1)
  expect((await attachments(page)).filter((r: any) => r.appId === 'notes')).toHaveLength(1)
})

test('a changed port invalidates a hidden app view before the next visit', async ({ page }) => {
  await open(page)
  await success(page, await select(page))
  await expect(page.frameLocator('iframe[data-framework]').getByRole('textbox', { name: 'App note' })).toBeVisible()
  await page.getByRole('button', { name: 'Other chat', exact: true }).click()
  await page.evaluate(apps => (window as any).panelReceive({ type: 'agent_app_framework_list', data: {
    status: 'success', data: { apps: [{ ...apps[0], port: 8899 }, apps[1]], connected: [] },
  } }), apps)
  await expect(page.locator('iframe[data-framework]')).toHaveCount(0)
  await page.getByRole('button', { name: 'Open Framework notes', exact: true }).click()
  await expect(view(page).getByText('Checking the app…', { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_open' && r.appId === 'notes').length)).toBe(2)
})

test('a failed conversation attachment can retry without reloading the app', async ({ page }) => {
  await open(page)
  await success(page, await select(page))
  await expect.poll(async () => (await attachments(page)).length).toBe(1)
  const req = (await attachments(page))[0]
  await page.evaluate(req => (window as any).panelReceive({ type: 'agent_app_framework_response', data: { requestId: req.requestId, status: 'error', message: 'Temporary attachment failure' } }), req)
  await expect(page.getByText('Could not open the app conversation.')).toBeVisible()
  const frame = page.frameLocator('iframe[data-framework]')
  await frame.getByRole('textbox', { name: 'App note' }).fill('Keep this app edit')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(async () => (await attachments(page)).length).toBe(2)
  await attachReply(page, (await attachments(page))[1])
  await expect(page.getByPlaceholder('Ask about this Agent App…')).toBeVisible()
  await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Keep this app edit')
})

test('the registry chat stacks below the app and resizes vertically on mobile', async ({ page }) => {
  await open(page)
  await success(page, await select(page))
  await expect.poll(async () => (await attachments(page)).length).toBe(1)
  await attachReply(page, (await attachments(page))[0])
  await page.setViewportSize({ width: 600, height: 850 })
  const composer = page.getByPlaceholder('Ask about this Agent App…')
  const seam = page.getByRole('button', { name: 'Hide Chat', exact: true })
  await expect(composer).toBeInViewport()
  const bounds = (await seam.boundingBox())!
  const app = (await page.locator('iframe[data-framework]').boundingBox())!
  expect(bounds.y).toBeGreaterThan(app.y)
  expect(Math.abs(bounds.y - app.y - app.height)).toBeLessThanOrEqual(2)
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y)
  await page.mouse.down()
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y - 60, { steps: 10 })
  await page.mouse.up()
  await expect.poll(async () => (await seam.boundingBox())!.y).toBeLessThan(bounds.y - 40)
  await seam.press('Enter')
  await expect(composer).not.toBeInViewport()
  await page.getByRole('button', { name: 'Show Chat', exact: true }).press('Enter')
  await expect(composer).toBeInViewport()
})

test('the dedicated side chat keeps Main untouched and shows activity on its app row', async ({ page }) => {
  await open(page)
  await page.evaluate(() => {
    const f = window as any
    f.panelReceive({ type: 'session_list', data: { sessions: [
      { id: 'main', type: 'main', title: 'Main' },
      { id: 'app-chat', type: 'chat', title: 'Framework notes' },
    ].map(session => ({ ...session, createdAt: '2026-11-10', lastActiveAt: '2026-11-10' })) } })
    f.panelReceive({ type: 'chat_history', data: { sessionId: 'main', messages: [{ messageId: 'main-before', sender: 'You', style: 'user', content: 'Main stays separate', timestamp: 1 }], hasMore: false } })
    f.panelReceive({ type: 'chat_history', data: { sessionId: 'app-chat', messages: [{ messageId: 'app-before', sender: 'You', style: 'user', content: 'Previous app conversation', timestamp: 1 }], hasMore: false } })
  })
  await expect(page.getByRole('button', { name: /^Framework notes(?: New messages)?$/ })).toBeVisible()
  await success(page, await select(page))
  await expect.poll(async () => (await attachments(page)).length).toBe(1)
  // The backend upgrades the existing session; its id and history stay intact.
  await page.evaluate(() => (window as any).panelReceive({ type: 'session_updated', data: { session: {
    id: 'app-chat', type: 'agent_app', title: 'Framework notes', agentAppFrameworkKey: JSON.stringify(['/home', '/framework/notes', 'notes']),
    createdAt: '2026-11-10', lastActiveAt: '2026-11-10',
  } } }))
  await attachReply(page, (await attachments(page))[0], 'app-chat')
  await expect(page.getByRole('button', { name: /^Framework notes(?: New messages)?$/ })).toHaveCount(0)
  await expect(page.getByText('Previous app conversation', { exact: true })).toBeVisible()
  const composer = page.getByPlaceholder('Ask about this Agent App…')
  await composer.fill('Only send to this app')
  await composer.press('Enter')
  await expect.poll(() => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'message').at(-1)?.sessionId)).toBe('app-chat')
  await expect(page.getByRole('button', { name: 'Open Framework notes', exact: true }).getByLabel('Agent working')).toBeVisible()
  await expect(page.getByRole('button', { name: /Main About the Main chat/ }).getByLabel('Agent working')).toHaveCount(0)
  const main = await page.evaluate(() => {
    const state = (window as any).panelStore.getState()
    return state.messages.bySession.main.items.map((message: any) => message.content)
  })
  expect(main).toEqual(['Main stays separate'])
  await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click()
  await expect(page.getByRole('button', { name: /^Agent App/ }).getByLabel('Agent working')).toBeVisible()
})
