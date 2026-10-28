import { test, expect } from '@playwright/test'

test('a new query keeps its caret and suggestions after selecting a reference', async ({ page }) => {
  await page.goto('/tests/references.html')
  const input = page.locator('textarea')
  await input.fill('@pricing')
  await expect(page.getByRole('option', { name: /Pricing discussion/ })).toBeVisible()

  // Hold the next paint so the following edit happens before any deferred
  // selection restoration. Advancing afterwards must not rewind its caret.
  await page.clock.install({ time: new Date('2030-01-01T00:00:00Z') })
  await page.clock.pauseAt(new Date('2030-01-01T00:00:01Z'))
  await input.press('Enter')
  await expect(input).toHaveValue('')
  await input.fill('@research')
  await page.clock.runFor(32)

  await expect(input).toHaveValue('@research')
  expect(await input.evaluate((element: HTMLTextAreaElement) => element.selectionStart)).toBe(9)
  await expect(page.getByRole('option', { name: /Research notes/ })).toBeVisible()
})
