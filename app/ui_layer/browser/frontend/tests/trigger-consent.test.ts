import { test, expect } from '@playwright/test'

test('nested dialogs isolate background, handle Escape once and restore focus in order', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?modal-test')
  await page.evaluate(() => {
    const existing = document.createElement('aside')
    existing.id = 'already-inert'
    existing.inert = true
    document.body.append(existing)
  })
  const opener = page.getByRole('button', { name: 'Open parent' })
  await opener.click()
  const parent = page.getByRole('dialog', { name: 'Parent dialog' })
  const childOpener = parent.getByRole('button', { name: 'Open child' })
  await childOpener.click()
  const child = page.getByRole('dialog', { name: 'Child dialog' })
  await expect(child).toBeFocused()
  expect(await parent.evaluate(el => el.closest('[inert]') !== null)).toBe(true)
  await childOpener.focus()
  await expect(child).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(child).toHaveCount(0)
  await expect(childOpener).toBeFocused()
  await page.evaluate(() => {
    const button = document.createElement('button')
    button.id = 'late-background'
    button.textContent = 'New background portal'
    document.body.append(button)
  })
  await expect(page.locator('#late-background')).toHaveAttribute('inert', '')
  await page.keyboard.press('Escape')
  await expect(parent).toHaveCount(0)
  await expect(opener).toBeFocused()
  await expect(page.locator('#already-inert')).toHaveAttribute('inert', '')
  await expect(page.locator('#late-background')).not.toHaveAttribute('inert', '')
})

test('dialog with no interactive controls retains focus in both Tab directions', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?modal-test&empty-modal')
  await page.getByRole('button', { name: 'Open parent' }).click()
  const dialog = page.getByRole('dialog', { name: 'Parent dialog' })
  await page.keyboard.press('Tab')
  await expect(dialog).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(dialog).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Open parent' })).toBeFocused()
})
