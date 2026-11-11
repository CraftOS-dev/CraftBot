import { test, expect, type Page } from '@playwright/test'

// Settings > Proactive: one switch, planners on an aligned grid, readable
// descriptions, and edits saved as proactive_schedule_set.
async function open(page: Page, query = '') {
  await page.goto(`/tests/panel-proactive-settings.html${query}`)
  await expect(page.getByRole('heading', { name: 'Planners' })).toBeVisible()
}

const requests = (page: Page) => page.evaluate(() => (window as unknown as { proactiveRequests: Record<string, unknown>[] }).proactiveRequests)

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
  test(`planner controls line up and descriptions are readable (${theme})`, async ({ page }) => {
    await open(page)
    await page.evaluate(t => document.documentElement.setAttribute('data-theme', t), theme)

    // One master switch: the heartbeat has no switch of its own.
    await expect(page.getByText('Heartbeat', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('checkbox', { name: 'Enable Proactive Mode' })).toBeChecked()

    // Every "Time" input starts at the same x; so do the "Runs on" cells.
    const times = ['Daily Planner', 'Weekly Planner', 'Monthly Planner'].map(n => page.getByLabel(`${n}: Time`))
    const timeX = await Promise.all(times.map(async l => (await l.boundingBox())!.x))
    expect(new Set(timeX.map(Math.round)).size).toBe(1)
    const weekDay = (await page.getByLabel('Weekly Planner: Runs on').boundingBox())!
    const monthDay = (await page.getByLabel('Monthly Planner: Runs on').boundingBox())!
    expect(Math.round(weekDay.x)).toBe(Math.round(monthDay.x))

    // Descriptions meet 4.5:1 against their row.
    const desc = page.getByText('Plans your day and sends a morning brief')
    const [fg, bg] = await desc.evaluate(el => [getComputedStyle(el).color, getComputedStyle(el.closest('div[class*="plannerRow"]')!).backgroundColor])
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5)

    await page.screenshot({ path: `test-results/proactive-settings-${theme}.png`, fullPage: true })
  })
}

test('editing a planner and the catch-up interval saves only what changed', async ({ page }) => {
  await open(page)
  await page.getByLabel('Weekly Planner: Runs on').selectOption('friday')
  await expect.poll(async () => (await requests(page)).filter(r => r.type === 'proactive_schedule_set')).toEqual([
    { type: 'proactive_schedule_set', weekPlannerDay: 'friday', weekPlannerHour: 17, weekPlannerMinute: 0 },
  ])
  await page.getByLabel('Catch up on missed tasks').selectOption('60')
  await expect.poll(async () => (await requests(page)).filter(r => r.type === 'proactive_schedule_set').length).toBe(2)
  const last = (await requests(page)).filter(r => r.type === 'proactive_schedule_set').at(-1)
  expect(last).toMatchObject({ heartbeatMinutes: 60 })
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
