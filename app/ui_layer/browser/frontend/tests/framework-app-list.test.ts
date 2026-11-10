import { expect, test, type Page } from '@playwright/test'

const registry = (page: Page) => page.getByRole('region', { name: 'Discovered apps', exact: true })
const options = (page: Page) => registry(page).getByRole('button', { name: 'Options: Framework notes', exact: true })
const notes = (page: Page) => registry(page).getByRole('button', { name: 'Open Framework notes', exact: true })
const refresh = (page: Page) => page.getByRole('button', { name: 'Refresh apps', exact: true })
const receive = (page: Page, data: unknown) => page.evaluate(data =>
  (window as any).panelReceive({ type: 'agent_app_framework_list', data }), data)
const snapshot = {
  status: 'success',
  data: {
    apps: [
      { id: 'notes', name: 'Framework notes', path: '/framework/notes', status: 'running' },
      { id: 'stopped', name: 'Quiet app', path: '/framework/quiet', status: 'stopped' },
      { id: 'missing', name: 'Moved app', path: '/framework/moved', status: 'missing' },
      { id: 'unreachable', name: 'Busy port', path: '/framework/busy', status: 'unreachable' },
    ],
    connected: [
      { appId: 'shared', name: 'Shared tracker', origin: 'https://example.test', credentialId: 'one', principalName: 'Member', status: 'online' },
      { appId: 'expired', name: 'Expired sign-in', origin: 'https://expired.test', credentialId: 'two', principalName: 'Member', status: 'expired' },
    ],
  },
}

async function open(page: Page) {
  await page.setViewportSize({ width: 1280, height: 960 })
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await expect(page.getByRole('button', { name: 'Collapse sidebar', exact: true })).toBeVisible()
  await receive(page, snapshot)
  await page.getByRole('button', { name: 'Show more (4)', exact: true }).click()
}

test('sidebar lists framework and connected apps without exposing legacy controls', async ({ page }, testInfo) => {
  await open(page)
  await expect(page.getByRole('button', { name: 'Notes', exact: true })).toBeVisible()
  await expect(registry(page).getByRole('listitem')).toHaveCount(9)
  for (const [name, status] of [['Framework notes', 'Running'], ['Quiet app', 'Stopped'], ['Moved app', 'App folder missing'], ['Busy port', 'Unavailable']]) {
    await expect(registry(page).getByRole('button', { name: `Open ${name}`, exact: true })).toHaveAttribute('title', new RegExp(status))
  }
  await expect(registry(page).getByRole('listitem').filter({ hasText: 'Shared tracker' })).toHaveAttribute('title', /Connected.*Online/)
  await expect(registry(page).getByRole('listitem').filter({ hasText: 'Expired sign-in' })).toHaveAttribute('title', /Connected.*Sign-in expired/)
  await expect(page.getByText('Discovered apps', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Create or install an app' })).toHaveCount(0)
  await expect(registry(page).getByRole('button', { name: /^(Start|Stop) / })).toHaveCount(0)
  await expect(registry(page).getByRole('button')).toHaveCount(14)
  await registry(page).getByText('Framework notes', { exact: true }).click()
  const state = await page.evaluate(() => {
    const fixture = window as any
    return { projects: fixture.panelStore.getState().agentApp.projects,
      calls: fixture.panelRequests.filter((r: any) => ['agent_app_launch', 'agent_app_stop', 'agent_app_delete'].includes(r.type)) }
  })
  expect(state.projects.map((p: any) => p.name)).toEqual(['Notes', 'Calendar', 'Weather'])
  expect(state.calls).toEqual([])
  await page.getByRole('complementary').screenshot({ path: testInfo.outputPath('registry-sidebar.png') })
})

test('automatic list updates retain stale data on errors and recover without a refresh button', async ({ page }) => {
  await open(page)
  await options(page).click()
  await expect(refresh(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'App settings', exact: true })).toHaveCount(0)
  await receive(page, { status: 'loading' })
  await expect(page.getByRole('button', { name: 'Stop Framework notes', exact: true })).toBeEnabled()
  await expect(notes(page)).not.toHaveAttribute('title', /Last known/)
  await expect(registry(page).getByText('Checking for apps…', { exact: true })).toHaveCount(0)
  await receive(page, { status: 'error', message: 'CLI timed out' })
  await expect(registry(page).getByRole('alert')).toHaveText("Couldn't load the app list.")
  await expect(registry(page).getByRole('listitem')).toHaveCount(9)
  await expect(refresh(page)).toHaveCount(0)
  await receive(page, { status: 'success', data: { apps: [{ ...snapshot.data.apps[0], status: 'stopped' }], connected: [] } })
  await expect(registry(page).getByRole('alert')).toHaveCount(0)
  await expect(registry(page).getByRole('listitem')).toHaveCount(4)
  await expect(notes(page)).toHaveAttribute('title', /Stopped/)
})

test('legacy snapshots and reconnects cannot erase or mislabel framework data', async ({ page }) => {
  await open(page)
  await page.evaluate(() => {
    const fixture = window as any
    fixture.panelReceive({ type: 'agent_app_list', data: { success: true, projects: [] } })
    fixture.panelStore.dispatch({ type: 'connection/setConnected', payload: false })
  })
  await expect(registry(page).getByRole('listitem')).toHaveCount(6)
  await options(page).click()
  await expect(notes(page)).toHaveAttribute('title', /Last known: Running/)
  await expect(refresh(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Stop Framework notes', exact: true })).toBeDisabled()
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: true }))
  await receive(page, snapshot)
  await expect(notes(page)).toHaveAttribute('title', /Framework notes · Running/)
  await receive(page, { status: 'success', data: { apps: [], connected: [] } })
  await expect(registry(page)).toHaveCount(0)
  await expect(page.getByText('No Agent App apps', { exact: true })).toBeVisible()
})

test('a framework diagnostic is visible even when its successful list is empty', async ({ page }) => {
  await open(page)
  await receive(page, { status: 'success', data: { apps: [], connected: [] }, stderr: 'The damaged registry was kept for recovery.' })
  await registry(page).getByText('App registry notice', { exact: true }).click()
  await expect(registry(page).getByText('The damaged registry was kept for recovery.', { exact: true })).toBeVisible()
  await receive(page, { status: 'success', data: { apps: [], connected: [] }, stderr: '' })
  await expect(registry(page).locator('details')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Notes', exact: true })).toBeVisible()
})

test('an initial query failure does not claim that no apps exist', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await expect(page.getByRole('button', { name: 'Collapse sidebar', exact: true })).toBeVisible()
  await page.evaluate(() => (window as any).panelReceive({ type: 'agent_app_list', data: { success: true, projects: [] } }))
  await receive(page, { status: 'error', message: 'CLI unavailable' })
  await expect(registry(page).getByRole('alert')).toBeVisible()
  await expect(refresh(page)).toHaveCount(0)
  await expect(page.getByText('No Agent App apps', { exact: true })).toHaveCount(0)
})

test('collapsed sidebar flyout keeps only lifecycle and deletion in its app menu', async ({ page }, testInfo) => {
  await open(page)
  await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click()
  await page.getByRole('button', { name: 'Agent App', exact: true }).click()
  await expect(page.getByRole('menu').getByRole('region', { name: 'Discovered apps' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add Agent App', exact: true })).toBeVisible()
  await expect(registry(page).getByText('Framework notes', { exact: true })).toBeVisible()
  await page.getByRole('menu').screenshot({ path: testInfo.outputPath('registry-flyout.png') })
  await options(page).click()
  await expect(refresh(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'App settings', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Stop Framework notes', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Delete', exact: true })).toBeVisible()
})

test('one five-app fold keeps chats visible and registry rows share saved drag order', async ({ page }, info) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await expect(page.getByRole('button', { name: 'Collapse sidebar', exact: true })).toBeVisible()
  await receive(page, snapshot)
  await expect(registry(page).getByRole('listitem')).toHaveCount(5)
  await expect(page.getByRole('button', { name: 'Show more (4)', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'dest', exact: true })).toBeInViewport()
  await page.getByRole('complementary').screenshot({ path: info.outputPath('original-sidebar-fold.png') })
  const source = await notes(page).boundingBox()
  const target = await page.getByRole('button', { name: 'Notes', exact: true }).boundingBox()
  await page.mouse.move(source!.x + 60, source!.y + source!.height / 2)
  await page.mouse.down()
  await page.mouse.move(target!.x + 60, target!.y + target!.height / 2, { steps: 12 })
  await page.mouse.up()
  await expect(registry(page).getByRole('listitem').first()).toContainText('Framework notes')
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_open'))).toEqual([])
  await page.reload()
  await expect(page.getByRole('button', { name: 'Collapse sidebar', exact: true })).toBeVisible()
  await receive(page, snapshot)
  await expect(registry(page).getByRole('listitem').first()).toContainText('Framework notes')
  await page.getByRole('button', { name: 'Show more (4)', exact: true }).click()
  await expect(registry(page).getByRole('listitem')).toHaveCount(9)
  await page.getByRole('button', { name: 'Show less', exact: true }).click()
  await expect(registry(page).getByRole('listitem')).toHaveCount(5)
})
