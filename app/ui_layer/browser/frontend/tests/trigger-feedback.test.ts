import { expect, test, type Page } from '@playwright/test'

const declined = {
  revision: 'feedback-v1', required: true, needsReview: false,
  triggers: [{ name: 'summarize', description: 'Summarize a recording', instruction: 'Summarize the selected recording.', change: 'new' }],
}
// Requests nobody has decided on yet; "declined" is after "Don't allow".
const pending = { ...declined, needsReview: true }
const receive = (page: Page, type: string, data: unknown) => page.evaluate(({ type, data }) => (window as any).panelReceive({ type, data }), { type, data })
const warningText = (name = 'Notes') => `${name} couldn't run a request because permission is required.`
const warning = (page: Page, name = 'Notes') => page.getByRole('status').filter({ hasText: warningText(name) })
const banner = (page: Page) => page.getByRole('status', { name: 'Agent request permissions', exact: true })
const dialog = (page: Page) => page.getByRole('dialog')
async function open(page: Page) {
  await page.goto('/tests/panel-agent-apps.html')
  await expect(page.getByRole('button', { name: 'Show an agent app', exact: true })).toBeVisible()
}
async function blocked(page: Page, projectId = 'notes', consent = declined, requestId = 'row-1') {
  await receive(page, 'agent_app_trigger_blocked', {
    projectId, projectName: projectId === 'notes' ? 'Notes' : 'Calendar', trigger: 'summarize', requestId, consent,
  })
}
// Closing the review is "Don't allow": it saves a decline, then closes.
async function closeDeclining(page: Page, projectId = 'notes', consent = declined) {
  await dialog(page).getByRole('button', { name: 'Close', exact: true }).click()
  const sent = await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_trigger_consent').at(-1))
  expect(sent).toMatchObject({ projectId, allow: false })
  await receive(page, 'agent_app_trigger_consent', { projectId, requestId: sent.requestId, success: true, consent })
  await expect(dialog(page)).toHaveCount(0)
}
async function catalogConsent(page: Page, consent = declined) {
  await page.evaluate(consent => {
    const fixture = window as any
    fixture.panelReceive({ type: 'agent_app_list', data: { success: true,
      projects: fixture.panelStore.getState().agentApp.projects.map((p: any) => p.id === 'notes' ? { ...p, triggerConsent: consent } : p),
    } })
  }, consent)
}

test('a blocked request in another chat shows one actionable notification per app/revision', async ({ page }, testInfo) => {
  await open(page)
  await blocked(page)
  await expect(warning(page)).toBeVisible()
  await expect(warning(page)).toContainText("Blocked requests won't run automatically.")
  for (let index = 0; index < 12; index++) await blocked(page, 'notes', declined, `row-${index + 2}`)
  await expect(page.getByText(warningText(), { exact: true })).toHaveCount(1)
  await expect(warning(page)).toHaveCSS('transform', 'none')
  const screenshot = testInfo.outputPath('blocked-request-chat.png')
  await page.screenshot({ path: screenshot })
  await warning(page).getByRole('button', { name: 'Review requests' }).click()
  await expect(dialog(page)).toHaveAccessibleName('Agent App requesting access to CraftBot')
  await expect(dialog(page).getByRole('heading', { name: 'Notes', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as any).panelRequests.some((r: any) => r.type === 'agent_app_list'))).toBe(true)
  expect(await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_trigger_consent'))).toEqual([])
  await closeDeclining(page)
  await blocked(page)
  await expect(warning(page)).toHaveCount(0)
  await blocked(page, 'notes', { ...declined, revision: 'feedback-v2' })
  await expect(warning(page)).toBeVisible()
  await blocked(page, 'calendar')
  await expect(warning(page, 'Calendar')).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'permission is required.' })).toHaveCount(2)
})

for (const width of [320, 390]) {
  test(`blocked-request notification is readable and actionable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 568 })
    await open(page)
    await blocked(page)
    await expect(warning(page)).toHaveCSS('transform', 'none')
    await expect(warning(page).getByRole('button', { name: 'Review requests' })).toBeInViewport()
    const bounds = await warning(page).boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width)
    await page.screenshot({ path: testInfo.outputPath('blocked-request-phone.png') })
    await warning(page).getByRole('button', { name: 'Review requests' }).press('Enter')
    await expect(dialog(page)).toHaveAccessibleName('Agent App requesting access to CraftBot')
    await expect(dialog(page).getByRole('heading', { name: 'Notes', exact: true })).toBeVisible()
  })
}

for (const width of [1280, 390]) {
  test(`permission banner shows only while a decision is pending, without reloading the frame, at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 })
    await open(page)
    await page.getByRole('button', { name: 'Show an agent app', exact: true }).click()
    await page.getByRole('menuitemradio', { name: 'Notes', exact: true }).click()
    const note = page.frameLocator('iframe[title="Notes"]').getByRole('textbox', { name: 'App note' })
    await note.fill('Preserved while reviewing permissions')
    await catalogConsent(page, pending)
    await expect(dialog(page)).toBeVisible()
    // A review left undecided (closed while offline) keeps the banner.
    await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'agentApp/dismissTriggerReview',
      payload: { projectId: 'notes', revision: 'feedback-v1' } }))
    await expect(dialog(page)).toHaveCount(0)
    await expect(banner(page)).toContainText('Agent requests are off until you review and allow them.')
    await expect(banner(page)).toHaveCount(1)
    await expect(note).toHaveValue('Preserved while reviewing permissions')
    await expect(banner(page).getByRole('button', { name: 'Review requests' })).toBeInViewport()
    await page.screenshot({ path: testInfo.outputPath('permission-banner-panel.png') })
    await banner(page).getByRole('button', { name: 'Review requests' }).click()
    await expect(dialog(page)).toHaveAccessibleName('Agent App requesting access to CraftBot')
    await expect(dialog(page).getByRole('heading', { name: 'Notes', exact: true })).toBeVisible()
    // "Don't allow" is a decision: the banner goes, in the panel and on the page.
    await closeDeclining(page)
    await expect(banner(page)).toHaveCount(0)
    await page.getByRole('button', { name: 'Notes app page', exact: true }).click()
    await expect(banner(page)).toHaveCount(0)
    await expect(note).toHaveValue('Preserved while reviewing permissions')

    // Changed requests ask again; allowing them keeps the banner away.
    await catalogConsent(page, { ...pending, revision: 'feedback-v2' })
    await expect(dialog(page)).toBeVisible()
    await expect(banner(page)).toHaveCount(1)
    await page.screenshot({ path: testInfo.outputPath('permission-banner-page.png') })
    await dialog(page).getByRole('button', { name: 'Allow', exact: true }).click()
    const requestId = await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_trigger_consent').at(-1).requestId)
    const allowed = { ...declined, revision: 'feedback-v2', required: false, triggers: [{ ...declined.triggers[0], change: 'approved' }] }
    await receive(page, 'agent_app_trigger_consent', { projectId: 'notes', requestId, success: true, consent: allowed })
    await expect(dialog(page)).toHaveCount(0)
    await expect(banner(page)).toHaveCount(0)
    await expect(note).toHaveValue('Preserved while reviewing permissions')
    await page.screenshot({ path: testInfo.outputPath('approved-page-no-banner.png') })
    await page.getByRole('button', { name: 'Back to chat', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Agent Apps panel', exact: true })).toBeVisible()
    await expect(banner(page)).toHaveCount(0)
    await expect(note).toHaveValue('Preserved while reviewing permissions')
    await page.screenshot({ path: testInfo.outputPath('approved-panel-no-banner.png') })
    await catalogConsent(page, { ...pending, revision: 'feedback-v3', triggers: [allowed.triggers[0],
      { name: 'send', description: 'Send a summary', instruction: 'Send it.', change: 'new' }] })
    await expect(banner(page)).toContainText('New or changed agent requests are off until you review them.')
  })
}

test('granting permission clears the warning and a later blocked request can notify again', async ({ page }) => {
  await open(page)
  await blocked(page)
  await expect(warning(page)).toBeVisible()
  const allowed = { ...declined, required: false, triggers: [{ ...declined.triggers[0], change: 'approved' }] }
  await receive(page, 'agent_app_trigger_consent', { projectId: 'notes', requestId: 'another-client', success: true, consent: allowed })
  await expect(warning(page)).toHaveCount(0)
  await catalogConsent(page)
  await expect(warning(page)).toHaveCount(0) // An old warning must not reappear on revocation alone.
  await blocked(page)
  await expect(warning(page)).toBeVisible()
  await receive(page, 'agent_app_list', { success: true, projects: [] })
  await expect(warning(page)).toHaveCount(0)
})

test('an already open approval dialog avoids a duplicate blocked notification', async ({ page }) => {
  await open(page)
  await blocked(page, 'notes', { ...declined, needsReview: true })
  await expect(dialog(page)).toBeVisible()
  await expect(warning(page)).toHaveCount(0)
  await closeDeclining(page)
  await blocked(page)
  await expect(warning(page)).toHaveCount(0)
})

test('notification can review an app not yet present in this browser catalog', async ({ page }) => {
  await open(page)
  await receive(page, 'agent_app_list', { success: true, projects: [] })
  await blocked(page, 'calendar')
  await warning(page, 'Calendar').getByRole('button', { name: 'Review requests' }).click()
  await expect(dialog(page)).toHaveCount(0)
  await page.evaluate(consent => (window as any).panelReceive({ type: 'agent_app_list', data: {
    success: true, projects: (window as any).panelProjects.map((p: any) => p.id === 'calendar' ? { ...p, triggerConsent: consent } : p),
  } }), declined)
  await expect(dialog(page)).toHaveAccessibleName('Agent App requesting access to CraftBot')
  await expect(dialog(page).getByRole('heading', { name: 'Calendar', exact: true })).toBeVisible()
})

test('a partial grant clears only the warning for the request that became allowed', async ({ page }) => {
  await open(page)
  await blocked(page)
  await expect(warning(page)).toBeVisible()
  await receive(page, 'agent_app_trigger_consent', { projectId: 'notes', success: true, consent: {
    ...declined, triggers: [{ ...declined.triggers[0], change: 'approved' },
      { name: 'send', description: 'Send a summary', instruction: 'Send it.', change: 'new' }],
  } })
  await expect(warning(page)).toHaveCount(0)
})

test('the permission banner leaves stopped-app controls reachable in a small phone panel', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 568 })
  await open(page)
  await page.evaluate(consent => {
    const fixture = window as any
    fixture.panelReceive({ type: 'agent_app_list', data: { success: true,
      projects: fixture.panelProjects.map((p: any) => p.id === 'weather' ? { ...p, triggerConsent: consent } : p),
    } })
  }, pending)
  await page.getByRole('button', { name: 'Show an agent app', exact: true }).click()
  await page.getByRole('menuitemradio', { name: 'Weather', exact: true }).click()
  await expect(banner(page).getByRole('button', { name: 'Review requests' })).toBeInViewport()
  const launch = page.getByRole('region', { name: 'Agent Apps panel', exact: true }).getByRole('button', { name: 'Launch', exact: true })
  await launch.scrollIntoViewIfNeeded()
  await expect(launch).toBeInViewport()
  await launch.click()
  expect(await page.evaluate(() => (window as any).panelRequests.some((r: any) => r.type === 'agent_app_launch' && r.projectId === 'weather'))).toBe(true)
})

test('approved app permissions can still be reviewed and revoked from its sidebar menu', async ({ page }, testInfo) => {
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await expect(page.getByRole('button', { name: 'Show an agent app', exact: true })).toBeVisible()
  const allowed = { ...declined, required: false, triggers: [{ ...declined.triggers[0], change: 'approved' }] }
  await catalogConsent(page, allowed)
  const row = page.getByRole('button', { name: 'Notes', exact: true }).locator('..')
  await row.hover()
  await row.getByRole('button', { name: 'Options', exact: true }).click()
  await page.screenshot({ path: testInfo.outputPath('review-requests-app-menu.png') })
  await page.getByRole('menu').getByRole('button', { name: 'Review requests', exact: true }).click()
  await expect(dialog(page)).toHaveAccessibleName('Agent App requesting access to CraftBot')
  await expect(dialog(page).getByRole('heading', { name: 'Notes', exact: true })).toBeVisible()
  await expect(dialog(page).getByText('Allowed', { exact: true })).toBeVisible()
  await dialog(page).getByRole('button', { name: "Don't allow" }).click()
  const requestId = await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_trigger_consent').at(-1).requestId)
  await receive(page, 'agent_app_trigger_consent', { projectId: 'notes', requestId, success: true, consent: declined })
  await expect(dialog(page)).toHaveCount(0)
  await expect(row).toBeVisible()
})
