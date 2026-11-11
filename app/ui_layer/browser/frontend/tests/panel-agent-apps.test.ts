import { expect, test, type Page } from '@playwright/test'

const appsButton = (page: Page) => page.getByRole('button', { name: 'Show an agent app', exact: true })
const appList = (page: Page) => page.getByRole('menu', { name: 'Agent apps', exact: true })
const appItems = (page: Page) => appList(page).locator('[role^="menuitem"]')
const appPanel = (page: Page) => page.getByRole('region', { name: 'Agent Apps panel', exact: true })
const note = (page: Page, app = 'Notes') => page.frameLocator(`iframe[title="${app}"]`).getByRole('textbox', { name: 'App note' })
const requests = (page: Page, types: string[]) => page.evaluate(types => (window as any).panelRequests.filter((r: any) => types.includes(r.type)), types)
const receive = (page: Page, type: string, data: unknown) => page.evaluate(({ type, data }) => (window as any).panelReceive({ type, data }), { type, data })

test('independent verification replaces stale builder progress in the app workspace', async ({ page }) => {
  const route = '/framework-app?path=C%3A%2Ftest%2Fnotes&id=notes'
  await page.goto(`/tests/panel-agent-apps.html?route=${encodeURIComponent(route)}`)
  await page.waitForFunction(() => typeof (window as any).panelReceive === 'function')
  const session = {
    id: 'notes-chat', type: 'agent_app', title: 'Notes',
    agentAppFrameworkKey: JSON.stringify(['test-home', 'C:/test/notes', 'notes']),
    agentAppBuild: { building: true, verifying: false, todos: [{ id: 'plan', content: 'Draft the plan', status: 'in_progress' }] },
  }
  await receive(page, 'session_updated', { session })
  await expect(page.getByText('Draft the plan', { exact: true })).toBeVisible()
  await receive(page, 'session_updated', { session: { ...session, agentAppBuild: { ...session.agentAppBuild, verifying: true } } })
  await expect(page.getByText('Independently testing the app…', { exact: true })).toBeVisible()
  await expect(page.getByText('Draft the plan', { exact: true })).toHaveCount(0)
  await receive(page, 'session_updated', { session })
  await expect(page.getByText('Independently testing the app…', { exact: true })).toHaveCount(0)
})

/** Ask the chat's apps button for an app and show it in the panel. */
async function show(page: Page, name: string) {
  await appsButton(page).click()
  await appList(page).getByRole('menuitemradio', { name, exact: true }).click()
  await expect(appList(page)).toHaveCount(0)
  await expect(appPanel(page)).toBeVisible()
  await expect(appsButton(page)).toHaveAttribute('title', name)
}

/** The chat's app is picked but hidden: one press shows it, with no menu. */
async function reopen(page: Page, name: string) {
  await appsButton(page).click()
  await expect(appPanel(page)).toBeVisible()
  await expect(appList(page)).toHaveCount(0)
  await expect(appsButton(page)).toHaveAttribute('title', name)
}

test('round Outputs, Browser and Agent Apps buttons; the apps button lists apps and Close', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await expect(page.getByRole('button', { name: "Show this chat's browser", exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(appsButton(page)).toHaveCSS('border-radius', '50%')
  // The sidebar's Agent Apps cube until the chat has an app.
  await expect(appsButton(page).locator('svg')).toHaveClass(/lucide-box/)
  await expect(page.getByRole('button', { name: 'Toggle panel' })).toHaveCount(0)
  await appsButton(page).click()
  // Just the apps: no "Agent apps" header, and no Close before there is an app.
  await expect(appItems(page)).toHaveText(['Notes', 'Calendar', 'Weather'])
  await expect(page.getByText('Agent apps', { exact: true })).toHaveCount(0)
  await expect(appsButton(page)).toHaveAttribute('aria-expanded', 'true')
  await expect(appList(page).getByRole('menuitemradio', { name: 'Notes', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(appList(page)).toHaveCount(0)
  await expect(appsButton(page)).toBeFocused()
  await expect(appPanel(page)).toHaveCount(0)
  await show(page, 'Notes')
  await expect(note(page)).toBeVisible()
  await expect(appsButton(page)).toHaveAttribute('data-shown', 'true')
  // No bar above the app: it fills the pane as on its own page.
  await expect(appPanel(page).getByRole('tablist')).toHaveCount(0)
  // Asked again, the chat's app is the one marked; another replaces it.
  await appsButton(page).click()
  await expect(appItems(page)).toHaveText(['Notes', 'Calendar', 'Weather', 'Close'])
  await expect(appList(page).getByRole('menuitemradio', { name: 'Notes', exact: true })).toHaveAttribute('aria-checked', 'true')
  await appList(page).getByRole('menuitemradio', { name: 'Calendar', exact: true }).click()
  await expect(appsButton(page)).toHaveAttribute('title', 'Calendar')
  await expect(note(page, 'Calendar')).toBeVisible()
  // Keyboard: open (on the chat's app), move, pick.
  await appsButton(page).press('ArrowDown')
  await expect(appList(page).getByRole('menuitemradio', { name: 'Calendar', exact: true })).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(appsButton(page)).toHaveAttribute('title', 'Weather')
  // Close: the chat no longer has an app; the button is the cube again.
  await appsButton(page).click()
  await appList(page).getByRole('menuitem', { name: 'Close', exact: true }).click()
  await expect(appPanel(page)).toHaveCount(0)
  await expect(appsButton(page)).toHaveAttribute('title', 'Show an agent app')
  await expect(appsButton(page).locator('svg')).toHaveClass(/lucide-box/)
  await appsButton(page).click()
  await expect(appList(page).getByRole('menuitem', { name: 'Close', exact: true })).toHaveCount(0)
})

test('a hidden app comes back with one press; the menu opens only while it is on show', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Notes')
  await note(page).fill('Kept')
  // Hide the panel by clicking its seam.
  await page.getByRole('separator', { name: 'Resize conversation and output', exact: true }).click()
  await expect(appPanel(page)).toHaveCount(0)
  await expect(appsButton(page)).toHaveAttribute('title', 'Notes')
  await reopen(page, 'Notes')
  await expect(note(page)).toHaveValue('Kept')
  // On show, the button opens the menu to switch or close.
  await appsButton(page).click()
  await expect(appList(page)).toBeVisible()
  await page.keyboard.press('Escape')
  // Hidden again, Arrow Down still reaches the menu.
  await page.getByRole('separator', { name: 'Resize conversation and output', exact: true }).click()
  await appsButton(page).press('ArrowDown')
  await expect(appList(page)).toBeVisible()
})

test('an app keeps its state across panel switches and full-page navigation', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Notes')
  await note(page).fill('Keep this draft')
  await expect(page.frameLocator('iframe[title="Notes"]').locator('#theme')).toHaveText('Waiting for theme')
  const boot = await page.locator('iframe[title="Notes"]').getAttribute('data-requested-src')
  await page.getByRole('button', { name: "Show this chat's browser", exact: true }).click()
  await expect(page.getByRole('region', { name: 'Browser panel', exact: true })).toBeVisible()
  await reopen(page, 'Notes')
  await expect(note(page)).toHaveValue('Keep this draft')
  await page.getByRole('button', { name: 'Notes app page', exact: true }).click()
  await expect(appPanel(page)).toHaveCount(0)
  await expect(note(page)).toHaveValue('Keep this draft')
  await page.getByRole('button', { name: 'Back to chat' }).click()
  await expect(appPanel(page)).toBeVisible()
  await expect(note(page)).toHaveValue('Keep this draft')
  expect(await page.locator('iframe[title="Notes"]').getAttribute('data-requested-src')).toBe(boot)
  await expect(page.locator('iframe[title="Notes"]')).toHaveCount(1)
})

test('showing, closing and switching apps never launch, stop or delete one', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Weather')
  await expect(appPanel(page).getByRole('button', { name: /^Start / })).toBeVisible()
  await appsButton(page).click()
  await appList(page).getByRole('menuitem', { name: 'Close', exact: true }).click()
  await expect(appPanel(page)).toHaveCount(0)
  await show(page, 'Notes')
  await show(page, 'Weather')
  expect(await requests(page, ['agent_app_framework_lifecycle'])).toEqual([])
})

test('launch is explicit and switches from a process status to the app view', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Weather')
  await appPanel(page).getByRole('button', { name: /^Start / }).click()
  await expect.poll(async () => (await requests(page, ['agent_app_framework_lifecycle'])).filter((r: any) => r.appId === 'weather').length).toBe(1)
  await page.evaluate(() => {
    const w = window as any
    const apps = w.panelProjects.map((p: any) => p.id === 'weather' ? { ...p, status: 'running', url: 'http://localhost:7935/tests/fixtures/panel-app.html' } : p)
    w.panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps, connected: [] } } })
    const request = w.panelRequests.findLast((r: any) => r.type === 'agent_app_framework_lifecycle')
    w.panelReceive({ type: request.type, data: { ...request, status: 'success' } })
  })
  await expect(note(page, 'Weather')).toBeVisible()
})

test('a failed start reports its error without leaving the app panel', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Weather')
  await appPanel(page).getByRole('button', { name: /^Start / }).click()
  await page.evaluate(() => {
    const w = window as any
    const request = w.panelRequests.findLast((r: any) => r.type === 'agent_app_framework_lifecycle')
    w.panelReceive({ type: request.type, data: { ...request, status: 'error', message: 'Failed to start Weather' } })
  })
  await expect(appPanel(page).getByText('Failed to start Weather')).toBeVisible()
  await expect(appPanel(page).getByRole('button', { name: /^Start / })).toBeEnabled()
})

test('each chat keeps its own app across reload, and failed catalogs do not forget it', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Notes')
  await page.getByRole('button', { name: 'Other chat', exact: true }).click()
  await expect(appPanel(page)).toHaveCount(0)
  await page.getByRole('button', { name: 'Back to chat' }).click()
  await expect(appPanel(page)).toBeVisible()
  await expect(appsButton(page)).toHaveAttribute('title', 'Notes')
  await page.evaluate(() => {
    (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: false })
    ;(window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'error', message: 'offline' } })
  })
  await expect(appsButton(page)).toHaveAttribute('title', 'Notes')
  await page.reload()
  await expect(appPanel(page)).toBeVisible()
  await expect(appsButton(page)).toHaveAttribute('title', 'Notes')
  expect(await requests(page, ['agent_app_framework_lifecycle'])).toEqual([])
})

test('a deleted app is forgotten and its frame disposed; stopping disposes the frame', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Notes')
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { connected: [], apps: (window as any).panelProjects.filter((p: any) => p.id !== 'notes') } } }))
  await expect(appPanel(page)).toHaveCount(0)
  await expect(page.locator('iframe[title="Notes"]')).toHaveCount(0)
  await appsButton(page).click()
  await expect(appList(page).getByRole('menuitemradio', { name: 'Notes', exact: true })).toHaveCount(0)
  await appList(page).getByRole('menuitemradio', { name: 'Calendar', exact: true }).click()
  await expect(note(page, 'Calendar')).toBeVisible()
  await page.evaluate(() => {
    const w = window as any
    const apps = w.panelProjects.filter((p: any) => p.id !== 'notes').map((p: any) => p.id === 'calendar' ? { ...p, status: 'stopped' } : p)
    w.panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps, connected: [] } } })
  })
  await expect(page.locator('iframe[title="Calendar"]')).toHaveCount(0)
  await expect(appPanel(page).getByRole('button', { name: /^Start / })).toBeVisible()
})

test('outputs and the browser can take the panel; the app comes back with its state', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Notes')
  await note(page).fill('Still here')
  await receive(page, 'mini_browser_activity', { sessions: [{ sessionId: 'dest', status: 'ready', browsing: true }] })
  await expect(page.getByRole('region', { name: 'Browser panel', exact: true })).toBeVisible()
  await reopen(page, 'Notes')
  await expect(note(page)).toHaveValue('Still here')
  await receive(page, 'chat_message', {
    messageId: 'output', sessionId: 'dest', sender: 'Agent', style: 'agent', content: 'Preview', timestamp: Date.now(),
    uiArtifact: { id: 'preview', title: 'Preview', revision: 1, html: '<p>Output preview</p>', connect_origins: [] },
  })
  await expect(page.getByRole('region', { name: 'Output panel', exact: true })).toBeVisible()
  await reopen(page, 'Notes')
  await expect(note(page)).toHaveValue('Still here')
})

test('a deployment navigates the existing app frame and repeated catalog pushes do not reload it', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Notes')
  await note(page).fill('Before deployment')
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { connected: [], apps: (window as any).panelProjects } } }))
  await expect(note(page)).toHaveValue('Before deployment')
  await page.evaluate(() => {
    const w = window as any
    const apps = w.panelProjects.map((p: any) => p.id === 'notes' ? { ...p, port: 7935, url: p.url + '?deployed' } : p)
    w.panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps, connected: [] } } })
  })
  await expect(note(page)).toHaveValue('')
  await expect(page.locator('iframe[title="Notes"]')).toHaveCount(1)
})

test('a stalled app navigation leaves the timeout and retry controls usable', async ({ page }) => {
  await page.clock.install()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  let navigations = 0
  await page.route('http://localhost:7935/tests/fixtures/panel-app.html*', route => {
    if (++navigations > 1) return route.continue()
    // Hold the first navigation pending; the browser cancels it on retry.
  })
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Notes')
  await expect(appPanel(page).getByText(/Loading the app view/)).toBeVisible()
  await page.clock.fastForward(21_000)
  await expect(appPanel(page).getByText(/hasn't finished loading/)).toBeVisible()
  await expect(page.locator('iframe[title="Notes"]')).toHaveCSS('visibility', 'hidden')
  await appPanel(page).getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(note(page)).toBeVisible()
})

test('an app that finishes loading while another is shown appears at once when picked again', async ({ page }) => {
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  // Hold only Notes (Calendar's URL carries ?calendar) until another app is shown.
  await page.route(url => url.pathname.endsWith('/tests/fixtures/panel-app.html') && !url.searchParams.has('calendar'),
    async route => { await held; await route.continue() })
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Notes')
  await expect(appPanel(page).getByText(/Loading the app view/)).toBeVisible()
  await show(page, 'Calendar')
  await expect(note(page, 'Calendar')).toBeVisible()
  release()
  await note(page).waitFor({ state: 'attached' })
  await show(page, 'Notes')
  await expect(note(page)).toBeVisible()
  await expect(appPanel(page).getByText(/Loading the app view/)).toHaveCount(0)
})

test('app references can open in the panel without submitting or switching the chat', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await page.waitForFunction(() => typeof (window as any).panelReceive === 'function')
  await receive(page, 'chat_history', { sessionId: 'dest', hasMore: false, messages: [{
    messageId: 'ref', sender: 'You', style: 'user', content: 'Use Notes', timestamp: Date.now(), sessionId: 'dest',
    references: [{ kind: 'agent_app', targetId: 'framework:["C:/test/notes","notes"]', label: 'Notes', capturedAt: '2026-10-26', excerpt: 'App metadata', truncated: false }],
  }] })
  await page.getByRole('button', { name: 'Notes', exact: true }).click()
  await page.getByRole('button', { name: 'Open in panel', exact: true }).click()
  await expect(appPanel(page)).toBeVisible()
  await expect(appsButton(page)).toHaveAttribute('title', 'Notes')
  expect(await requests(page, ['chat_message', 'agent_app_launch'])).toEqual([])
})

test("narrow layout aligns the frame; an app's own chat offers only outputs and the browser", async ({ page }) => {
  await page.setViewportSize({ width: 720, height: 950 })
  await page.goto('/tests/panel-agent-apps.html')
  await show(page, 'Notes')
  await expect.poll(async () => (await page.locator('iframe[title="Notes"]').boundingBox())?.width).toBeGreaterThan(600)
  await page.getByRole('button', { name: 'Notes app page', exact: true }).click()
  await expect(page.getByRole('button', { name: "Show this chat's browser", exact: true })).toBeVisible()
  await expect(appsButton(page)).toHaveCount(0)
})
