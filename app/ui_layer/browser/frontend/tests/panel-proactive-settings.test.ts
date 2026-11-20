import { test, expect, type Page } from '@playwright/test'

// Settings > Proactive: Cron Jobs, then the Heartbeat with the checklist it
// reads, then Planners on an aligned grid; plain descriptions with the
// technical details (PROACTIVE.md) in ⓘ tooltips; edits saved as their own
// messages.
async function open(page: Page, query = '') {
  await page.goto(`/tests/panel-proactive-settings.html${query}`)
  await expect(page.getByRole('heading', { name: 'Planners' })).toBeVisible()
}

const requests = (page: Page) => page.evaluate(() => (window as unknown as { proactiveRequests: Record<string, unknown>[] }).proactiveRequests)
const sent = async (page: Page, type: string) => (await requests(page)).filter(r => r.type === type)

function luminance(rgb: string) {
  const [r, g, b] = (rgb.match(/\d+/g) || []).slice(0, 3).map(Number).map(c => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

for (const theme of ['dark', 'light'] as const) {
  test(`sections, aligned controls and readable descriptions (${theme})`, async ({ page }) => {
    await open(page)
    await page.evaluate(t => document.documentElement.setAttribute('data-theme', t), theme)

    // Recurring Tasks first, then Heartbeat, then Planners.
    const headings = await page.getByRole('heading', { level: 4 }).allTextContents()
    expect(headings.slice(0, 3)).toEqual(['Recurring Tasks', 'Heartbeat', 'Planners'])
    await expect(page.getByText('Proactive Tasks')).toHaveCount(0)
    await expect(page.getByText('Cron Jobs')).toHaveCount(0)

    // The heartbeat shows what it reads; file names stay out of the page copy.
    await expect(page.getByLabel('Checklist')).toHaveValue('- Check my inbox for urgent email from clients')
    await expect(page.getByText('One item per line. The agent reads this on every tick; leave it empty and the heartbeat does not run.')).toBeVisible()
    await expect(page.getByText('PROACTIVE.md')).toHaveCount(0)

    // Every planner "Time" input starts at the same x; the heartbeat interval
    // spans the "Runs on" and "Time" columns.
    const times = ['Daily Planner', 'Weekly Planner', 'Monthly Planner'].map(n => page.getByLabel(`${n}: Time`))
    const timeBoxes = await Promise.all(times.map(async l => (await l.boundingBox())!))
    expect(new Set(timeBoxes.map(b => Math.round(b.x))).size).toBe(1)
    const weekDay = (await page.getByLabel('Weekly Planner: Runs on').boundingBox())!
    const interval = (await page.getByLabel('Interval').boundingBox())!
    expect(Math.round(interval.x)).toBe(Math.round(weekDay.x))
    expect(Math.round(interval.x + interval.width)).toBe(Math.round(timeBoxes[0].x + timeBoxes[0].width))

    // Descriptions meet 4.5:1 against their row.
    const desc = page.getByText('Plans your day and sends a morning brief')
    const [fg, bg] = await desc.evaluate(el => [getComputedStyle(el).color, getComputedStyle(el.closest('div[class*="plannerRow"]')!).backgroundColor])
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5)

    await page.screenshot({ path: `test-results/proactive-settings-${theme}.png`, fullPage: true })
  })
}

test('each section has an ⓘ tooltip on hover and keyboard focus', async ({ page }) => {
  await open(page)
  for (const name of ['About recurring tasks', 'About the heartbeat', 'About planners', 'About reset']) {
    await expect(page.getByLabel(name)).toBeVisible()
  }

  await page.getByLabel('About the heartbeat').hover()
  const tip = page.getByRole('tooltip')
  await expect(tip).toContainText('How the heartbeat works')
  await expect(tip).toContainText('Heartbeat section of PROACTIVE.md')
  const box = (await tip.boundingBox())!
  const viewport = page.viewportSize()!
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height)
  await page.mouse.move(0, 0)
  await expect(tip).toHaveCount(0)

  await page.getByLabel('About planners').focus()
  await expect(page.getByRole('tooltip')).toContainText("The daily planner sets the day's priorities")
  await page.screenshot({ path: 'test-results/proactive-settings-tooltip.png' })
})

test('recurring tasks are compact cards grouped by frequency, with icon details', async ({ page }) => {
  await open(page)
  const groups = page.locator('div[class*="jobGroupLabel"], span[class*="jobGroupLabel"]')
  await expect(groups).toHaveText(['Hourly', 'Daily', 'Weekly', 'Monthly'])

  const cards = page.locator('div[class*="jobCard"]')
  await expect(cards).toHaveCount(4)
  const details = await cards.evaluateAll(els => els.map(el => [...el.querySelectorAll('span[class*="jobMetaItem"]')].map(s => s.textContent)))
  expect(details).toEqual([
    [':15', 'Not run yet', '3 runs', 'Silent', 'Medium priority'],
    ['08:30', 'Last run Nov 11, 08:30', '12 runs', 'Reports results', 'High priority'],
    ['Friday, 17:00', 'Not run yet', 'Reports results', 'Medium priority'],
    ['Day 1, 09:00', 'Last run Nov 1, 09:00', '2 runs', 'Silent', 'Low priority'],
  ])
  // Every detail carries an icon; the controls line up on the name row.
  const icons = await cards.evaluateAll(els => els.every(el => [...el.querySelectorAll('span[class*="jobMetaItem"]')].every(s => s.querySelector('svg'))))
  expect(icons).toBe(true)
  const rights = await cards.evaluateAll(els => els.map(el => Math.round(el.querySelector('div[class*="jobControls"]')!.getBoundingClientRect().right)))
  expect(new Set(rights).size).toBe(1)
  // Reporting and priority end on the right edge, under the controls.
  const ends = await cards.evaluateAll(els => els.map(el => Math.round(el.querySelector('span[class*="jobMetaEnd"]')!.getBoundingClientRect().right)))
  for (const end of ends) expect(Math.abs(end - rights[0])).toBeLessThanOrEqual(1)
  // Compact: a one-line instruction card stays under 96px tall.
  const height = (await cards.nth(1).boundingBox())!.height
  expect(height).toBeLessThan(96)

  await page.locator('div[class*="jobGroups"]').screenshot({ path: 'test-results/proactive-recurring-tasks.png' })

  // Each task names the chat it runs in; a task whose chat was deleted is
  // kept, says so, and can be moved to the main chat.
  await expect(cards.nth(1).locator('span[class*="jobChatName"]')).toHaveText('Main chat')
  await expect(cards.nth(2).locator('span[class*="jobChatName"]')).toHaveText('Sales follow-ups')
  const clipped = await cards.nth(2).locator('span[class*="jobChatName"]').evaluate(el => el.scrollWidth > el.clientWidth)
  expect(clipped).toBe(false)
  const orphan = cards.nth(3)
  await expect(orphan.locator('span[class*="jobChatName"]')).toHaveCount(0)
  await expect(orphan.getByRole('status')).toContainText('Unavailable: the chat this task runs in was deleted.')
  await orphan.getByRole('button', { name: 'Move to main chat' }).click()
  await expect.poll(() => sent(page, 'cron_job_update')).toEqual([
    { type: 'cron_job_update', jobId: 'monthly_invoices', updates: { sessionId: 'main' } },
  ])

  // Switch and actions are named per task.
  await expect(page.getByRole('checkbox', { name: 'Inbox watch' })).not.toBeChecked()
  await page.getByRole('button', { name: 'Edit: Morning brief' }).click()
  await expect(page.getByRole('heading', { name: 'Edit Recurring Task' })).toBeVisible()
})

test('editing a planner and the heartbeat interval saves only what changed', async ({ page }) => {
  await open(page)
  await page.getByLabel('Weekly Planner: Runs on').selectOption('friday')
  await expect.poll(() => sent(page, 'proactive_schedule_set')).toEqual([
    { type: 'proactive_schedule_set', weekPlannerDay: 'friday', weekPlannerHour: 17, weekPlannerMinute: 0 },
  ])
  await page.getByLabel('Interval').selectOption('60')
  await expect.poll(async () => (await sent(page, 'proactive_schedule_set')).length).toBe(2)
  expect((await sent(page, 'proactive_schedule_set')).at(-1)).toMatchObject({ heartbeatMinutes: 60 })
})

test('the checklist saves when the box loses focus', async ({ page }) => {
  await open(page)
  const box = page.getByLabel('Checklist')
  await box.fill('- Check my inbox for urgent email from clients\n- Tell me if the nightly build fails')
  expect(await sent(page, 'heartbeat_checklist_set')).toEqual([])
  await page.getByRole('heading', { name: 'Planners' }).click()
  await expect.poll(() => sent(page, 'heartbeat_checklist_set')).toEqual([
    { type: 'heartbeat_checklist_set', checklist: '- Check my inbox for urgent email from clients\n- Tell me if the nightly build fails' },
  ])
})

test('the heartbeat has its own switch, and an empty checklist reads as not running', async ({ page }) => {
  await open(page)
  // The switch follows the server's reply (no optimistic flip), like the planners.
  await page.getByRole('checkbox', { name: 'Heartbeat' }).click()
  await expect.poll(() => sent(page, 'scheduler_config_update')).toEqual([
    { type: 'scheduler_config_update', updates: { schedules: [{ id: 'heartbeat', enabled: false }] } },
  ])
  await page.getByLabel('Checklist').fill('')
  await expect(page.getByText('Inactive: the checklist is empty')).toBeVisible()
})

test('a planner that is off keeps its schedule but cannot be edited', async ({ page }) => {
  await open(page)
  await expect(page.getByLabel('Monthly Planner: Runs on')).toBeDisabled()
  await expect(page.getByLabel('Monthly Planner: Runs on')).toHaveValue('1')
  await expect(page.getByLabel('Daily Planner: Time')).toBeEnabled()
})

test('narrow panel stacks controls under the name without overflow', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 900 })
  await open(page, '?width=380')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(overflow).toBe(false)
  await page.screenshot({ path: 'test-results/proactive-settings-narrow.png', fullPage: true })
})
