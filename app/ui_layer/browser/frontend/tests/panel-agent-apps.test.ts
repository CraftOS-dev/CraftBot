import { expect, test, type Page } from '@playwright/test'

const chooser = (page: Page) => page.getByRole('region', { name: 'Open in panel', exact: true })
const panel = (page: Page) => page.getByRole('region', { name: /^(Agent Apps panel|Open in panel)$/ })
async function toggleApps(page: Page) {
  const trigger = page.getByRole('button', { name: 'Toggle panel', exact: true })
  if (await panel(page).count()) { await trigger.click(); return }
  if (await trigger.getAttribute('aria-expanded') !== 'true') await trigger.click()
  const appTabs = page.locator('[data-tab-id^="app:"] [role="tab"]')
  if (await appTabs.count()) await appTabs.first().click()
}
async function add(page: Page, name: string) {
  if (!await chooser(page).count()) await page.getByRole('button', { name: 'Open in panel', exact: true }).click()
  await chooser(page).getByRole('textbox', { name: 'Search apps and outputs' }).fill(name)
  await chooser(page).getByRole('button', { name, exact: true }).click()
  await expect(chooser(page)).toHaveCount(0)
}
async function open(page: Page) {
  await page.goto('/tests/panel-agent-apps.html')
  await toggleApps(page)
  await expect(chooser(page)).toBeVisible()
}

test('panel opens a content chooser with no pre-opened browser and a split-panel icon', async ({ page }, testInfo) => {
  await open(page)
  const trigger = page.getByRole('button', { name: 'Toggle panel', exact: true })
  await expect(trigger.locator('svg')).toHaveClass(/lucide-panel-left/)
  await expect(page.getByRole('tab', { name: 'Browser', exact: true })).toHaveCount(0)
  await expect(chooser(page).getByRole('button', { name: 'Browser', exact: true })).toBeVisible()
  await expect(chooser(page).getByRole('button', { name: 'Notes', exact: true })).toBeVisible()
  await expect(chooser(page).getByRole('button', { name: 'Weather', exact: true })).toBeVisible()
  await expect(page.getByRole('menu')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('panel-chooser.png'), animations: 'disabled' })
  await chooser(page).getByRole('button', { name: 'Browser', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Browser panel', exact: true })).toBeVisible()
  await trigger.click(); await trigger.click()
  await expect(chooser(page)).toBeVisible()
  await add(page, 'Notes')
  await expect(panel(page).getByRole('tab', { name: 'Notes', exact: true })).toHaveAttribute('aria-selected', 'true')
})

test('installed apps open in the panel, retain state across tabs and full-page navigation', async ({ page }) => {
  await open(page)
  await add(page, 'Notes')
  const frame = page.frameLocator('iframe[title="Notes"]')
  await frame.getByRole('textbox', { name: 'App note' }).fill('Keep this draft')
  await expect(frame.locator('#theme')).toHaveText('craftbot:dark')
  const boot = await page.locator('iframe[title="Notes"]').evaluate((el: HTMLIFrameElement) => el.dataset.requestedSrc)
  await add(page, 'Calendar')
  await panel(page).getByRole('tab', { name: 'Notes', exact: true }).click()
  await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Keep this draft')
  await panel(page).getByRole('button', { name: 'Open full app' }).click()
  await expect(page.getByRole('region', { name: 'Agent Apps panel' })).toHaveCount(0)
  await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Keep this draft')
  await page.getByRole('button', { name: 'Back to chat' }).click()
  await expect(panel(page)).toBeVisible()
  await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Keep this draft')
  expect(await page.locator('iframe[title="Notes"]').getAttribute('data-requested-src')).toBe(boot)
  await expect(page.locator('iframe[title="Notes"]')).toHaveCount(1)
})

test('attaching, hiding and detaching do not launch, stop or delete an app', async ({ page }) => {
  await open(page)
  await add(page, 'Weather')
  await expect(panel(page).getByRole('button', { name: 'Launch', exact: true })).toBeVisible()
  await toggleApps(page)
  await expect(panel(page)).toHaveCount(0)
  await toggleApps(page)
  await panel(page).getByRole('button', { name: 'Remove Weather from panel' }).click()
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) => ['agent_app_launch', 'agent_app_stop', 'agent_app_delete'].includes(r.type)))).toEqual([])
})

test('launch is explicit and switches from a process status to the app view', async ({ page }) => {
  await open(page)
  await add(page, 'Weather')
  await panel(page).getByRole('button', { name: 'Launch', exact: true }).click()
  await expect(panel(page).getByRole('tab', { name: 'Weather', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_launch' && r.projectId === 'weather').length)).toBe(1)
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_launch', data: { success: true, projectId: 'weather', url: 'http://localhost:7935/tests/fixtures/panel-app.html', port: 7935 } }))
  await expect(page.frameLocator('iframe[title="Weather"]').getByRole('textbox', { name: 'App note' })).toBeVisible()
})

test('process states keep the full app page guidance', async ({ page }) => {
  await open(page)
  await add(page, 'Weather')
  await panel(page).getByRole('button', { name: 'Launch', exact: true }).click()
  await expect(panel(page).getByText('Installing dependencies, running tests, starting servers')).toBeVisible()
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_launch', data: { success: false, projectId: 'weather' } }))
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_list', data: { success: true,
    projects: (window as any).panelProjects.map((p: any) => p.id === 'weather' ? { ...p, status: 'error' } : p) } }))
  await expect(panel(page).getByText('Unknown error', { exact: true })).toBeVisible()
})

test('per-chat tabs survive reload, and disconnected or failed catalogs do not prune them', async ({ page }) => {
  await open(page)
  await add(page, 'Notes')
  await page.getByRole('button', { name: 'Other chat', exact: true }).click()
  await toggleApps(page)
  await expect(panel(page).getByRole('tab', { name: 'Notes', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Back to chat' }).click()
  await expect(panel(page).getByRole('tab', { name: 'Notes', exact: true })).toBeVisible()
  await page.evaluate(() => {
    (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: false })
    ;(window as any).panelReceive({ type: 'agent_app_list', data: { success: false, projects: [] } })
  })
  await expect(panel(page).getByRole('tab', { name: 'Notes', exact: true })).toBeVisible()
  await page.reload()
  await expect(panel(page).getByRole('tab', { name: 'Notes', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_launch'))).toEqual([])
})

test('catalog deletion prunes tabs and disposes warm frames', async ({ page }) => {
  await open(page)
  await add(page, 'Notes')
  await add(page, 'Calendar')
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_list', data: { success: true, projects: (window as any).panelProjects.filter((p: any) => p.id !== 'notes') } }))
  await expect(panel(page).getByRole('tab', { name: 'Notes', exact: true })).toHaveCount(0)
  await expect(page.locator('iframe[title="Notes"]')).toHaveCount(0)
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_stop', data: { success: true, projectId: 'calendar' } }))
  await expect(page.locator('iframe[title="Calendar"]')).toHaveCount(0)
  await expect(panel(page).getByRole('button', { name: 'Launch', exact: true })).toBeVisible()
})

test('the inline chooser searches all content and preserves the app while choosing', async ({ page }) => {
  await open(page)
  await add(page, 'Notes')
  const note = page.frameLocator('iframe[title="Notes"]').getByRole('textbox', { name: 'App note' })
  await note.fill('Saved view')
  await page.getByRole('button', { name: 'Open in panel', exact: true }).click()
  const search = chooser(page).getByRole('textbox', { name: 'Search apps and outputs' })
  await search.fill('no such content')
  await expect(chooser(page).getByRole('status')).toHaveText('Nothing matches your search.')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await panel(page).getByRole('tab', { name: 'Notes', exact: true }).click()
  await expect(note).toHaveValue('Saved view')
})

test('browser and new outputs can take the panel while app attachments retain their state', async ({ page }) => {
  await open(page)
  await add(page, 'Notes')
  const note = page.frameLocator('iframe[title="Notes"]').getByRole('textbox', { name: 'App note' })
  await note.fill('Still here')
  await page.evaluate(() => (window as any).panelReceive({ type: 'mini_browser_activity', data: { sessions: [{ sessionId: 'dest', status: 'ready', browsing: true }] } }))
  await expect(panel(page)).toHaveCount(0)
  await toggleApps(page)
  await expect(note).toHaveValue('Still here')
  await page.evaluate(() => (window as any).panelReceive({ type: 'chat_message', data: {
    messageId: 'output', sessionId: 'dest', sender: 'Agent', style: 'agent', content: 'Preview', timestamp: Date.now(),
    uiArtifact: { id: 'preview', title: 'Preview', revision: 1, html: '<p>Output preview</p>', connect_origins: [] },
  } }))
  await expect(page.getByRole('region', { name: 'Output panel', exact: true })).toBeVisible()
  await toggleApps(page)
  await expect(note).toHaveValue('Still here')
  await panel(page).getByRole('button', { name: 'Close Preview', exact: true }).click()
  await expect(note).toHaveValue('Still here')
  const browserTab = panel(page).getByRole('tab', { name: 'Browser', exact: true })
  await browserTab.focus()
  await browserTab.press('Delete')
  await expect(panel(page)).toBeVisible()
  await expect(browserTab).toHaveCount(0)
})

test('a deployment navigates the existing app frame and repeated catalog pushes do not reload it', async ({ page }) => {
  await open(page)
  await add(page, 'Notes')
  const note = page.frameLocator('iframe[title="Notes"]').getByRole('textbox', { name: 'App note' })
  await note.fill('Before deployment')
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_list', data: { success: true, projects: (window as any).panelProjects } }))
  await expect(note).toHaveValue('Before deployment')
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_ready', data: { projectId: 'notes', url: 'http://localhost:7935/tests/fixtures/panel-app.html', port: 7935 } }))
  await expect(note).toHaveValue('')
  await expect(page.locator('iframe[title="Notes"]')).toHaveCount(1)
})

test('a stalled app navigation leaves the timeout and retry controls usable', async ({ page }) => {
  await page.clock.install()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.route('http://localhost:7935/tests/fixtures/panel-app.html*', route => {
    if (route.request().url().includes('viewRetry')) return route.continue()
    // Hold the first navigation pending; the browser cancels it on retry.
  })
  await open(page)
  await add(page, 'Notes')
  await expect(panel(page).getByText('Loading app view…')).toBeVisible()
  await page.clock.fastForward(21_000)
  await expect(panel(page).getByText(/taking longer to load/)).toBeVisible()
  await expect(page.locator('iframe[title="Notes"]')).toHaveCSS('visibility', 'hidden')
  await panel(page).getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.frameLocator('iframe[title="Notes"]').getByRole('textbox', { name: 'App note' })).toBeVisible()
})

test('an app that finishes loading in a background tab shows at once when its tab returns', async ({ page }) => {
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  // Hold only Notes (Calendar's URL carries ?calendar) until its tab is in the background.
  await page.route(url => url.pathname.endsWith('/tests/fixtures/panel-app.html') && !url.searchParams.has('calendar'),
    async route => { await held; await route.continue() })
  await open(page)
  await add(page, 'Notes')
  await expect(panel(page).getByText('Loading app view…')).toBeVisible()
  await add(page, 'Calendar')
  await expect(page.frameLocator('iframe[title="Calendar"]').getByRole('textbox', { name: 'App note' })).toBeVisible()
  release()
  await page.frameLocator('iframe[title="Notes"]').getByRole('textbox', { name: 'App note' }).waitFor({ state: 'attached' })
  await panel(page).getByRole('tab', { name: 'Notes', exact: true }).click()
  await expect(page.frameLocator('iframe[title="Notes"]').getByRole('textbox', { name: 'App note' })).toBeVisible()
  await expect(panel(page).getByText('Loading app view…')).toHaveCount(0)
})

test('app references can open in the panel without submitting or switching the chat', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await page.waitForFunction(() => typeof (window as any).panelReceive === 'function')
  await page.evaluate(() => (window as any).panelReceive({ type: 'chat_history', data: { sessionId: 'dest', hasMore: false, messages: [{
    messageId: 'ref', sender: 'You', style: 'user', content: 'Use Notes', timestamp: Date.now(), sessionId: 'dest',
    references: [{ kind: 'agent_app', targetId: 'notes', label: 'Notes', capturedAt: '2026-10-26', excerpt: 'App metadata', truncated: false }],
  }] } }))
  await page.getByRole('button', { name: 'Notes', exact: true }).click()
  await page.getByRole('button', { name: 'Open in panel', exact: true }).click()
  await expect(panel(page).getByRole('tab', { name: 'Notes', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'chat_message' || r.type === 'agent_app_launch'))).toEqual([])
})

test('narrow layout aligns the frame and collapsing the parent app chat hides nested frames', async ({ page }) => {
  await page.setViewportSize({ width: 720, height: 950 })
  await open(page)
  await add(page, 'Notes')
  await expect.poll(async () => (await page.locator('iframe[title="Notes"]').boundingBox())?.width).toBeGreaterThan(600)
  await panel(page).getByRole('button', { name: 'Open full app' }).click()
  await toggleApps(page)
  await expect(chooser(page).getByRole('button', { name: 'Notes', exact: true })).toHaveCount(0)
  await chooser(page).getByRole('button', { name: 'Calendar', exact: true }).click()
  await page.getByRole('button', { name: 'Hide Chat', exact: true }).click()
  await expect(page.locator('iframe[title="Calendar"]')).toHaveCSS('visibility', 'hidden')
})
