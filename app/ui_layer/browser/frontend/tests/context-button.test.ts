import { test, expect, type Page } from '@playwright/test'

const contextButton = (page: Page) => page.getByRole('button', { name: 'Context window', exact: true })
const menu = (page: Page) => page.getByRole('menu')
async function commands(page: Page) {
  return page.evaluate(() => (window as unknown as { fixtureRequests: Record<string, unknown>[] }).fixtureRequests.filter(r => r.type === 'command'))
}
async function updateSession(page: Page, patch: Record<string, unknown>) {
  await page.evaluate(patch => {
    const session = { ...(window as unknown as { fixtureSession: object }).fixtureSession, ...patch }
    window.dispatchEvent(new CustomEvent('fixture-response', { detail: { type: 'session_updated', data: { session } } }))
  }, patch)
}

test('the ring sits left of the mic and its menu holds the context and cache readout', async ({ page }) => {
  await page.goto('/tests/context-button.html')
  const ring = await contextButton(page).boundingBox()
  const mic = await page.getByTitle('Voice input', { exact: true }).boundingBox()
  expect(ring && mic && ring.x + ring.width <= mic.x).toBeTruthy()
  await expect(contextButton(page)).toHaveAttribute('title', 'Context 180K / 250K (72%)')

  await contextButton(page).click()
  await expect(menu(page).getByText('Context · gpt-test', { exact: true })).toBeVisible()
  await expect(menu(page).getByText('180K / 250K', { exact: true })).toBeVisible()
  await expect(menu(page).getByText('Summarizes at 250K', { exact: true })).toBeVisible()
  await expect(menu(page).getByText('83% cached', { exact: true })).toBeVisible()
  await expect(menu(page).getByText('Time left', { exact: true })).toBeVisible()
})

test('the reasoning menu no longer carries the readout', async ({ page }) => {
  await page.goto('/tests/context-button.html')
  await page.getByRole('button', { name: 'Reasoning effort', exact: true }).click()
  await expect(menu(page).getByRole('menuitemradio', { name: 'Medium Default' })).toBeVisible()
  await expect(menu(page).getByText('Summarizes at', { exact: false })).toHaveCount(0)
  await expect(menu(page).getByText('Cache', { exact: true })).toHaveCount(0)
})

test('fold now sends /fold, spins until done, then reads the folded size', async ({ page }) => {
  await page.goto('/tests/context-button.html')
  await contextButton(page).click()
  await menu(page).getByRole('menuitem', { name: /Fold now/ }).click()
  await expect.poll(() => commands(page)).toEqual([expect.objectContaining({ command: '/fold', sessionId: 'dest' })])
  await expect(menu(page).getByRole('menuitem', { name: /Folding/ })).toBeDisabled()

  const at = await page.evaluate(() => Date.now())
  await updateSession(page, { folding: false, lastFold: { at, freedTokens: 120_000 } })
  await expect(menu(page).getByText('~60K / 250K', { exact: true })).toBeVisible()
  await expect(menu(page).getByRole('menuitem', { name: /Fold now/ })).toBeEnabled()
  await expect(contextButton(page)).toHaveAttribute('title', 'Context 60K / 250K (24%)')

  // The next request reports the real size, and the estimate goes.
  await updateSession(page, {
    lastFold: { at, freedTokens: 120_000 },
    lastRequest: { inputTokens: 64_000, cachedTokens: 0, startedAt: at + 1000, surface: 'openai', model: 'gpt-test' },
  })
  await expect(menu(page).getByText('64K / 250K', { exact: true })).toBeVisible()
})

for (const theme of ['dark', 'light'])
  test(`screenshot (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 640 })
    await page.goto(`/tests/context-button.html${theme === 'light' ? '?light' : ''}`)
    await contextButton(page).click()
    await expect(menu(page)).toBeVisible()
    await page.screenshot({ path: `test-results/context-button-${theme}.png` })
    await contextButton(page).hover()
    await page.locator('textarea').screenshot({ path: `test-results/context-composer-${theme}.png` })
  })
