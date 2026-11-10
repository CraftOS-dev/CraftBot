import { expect, type Page } from '@playwright/test'

/** Follow the same Settings → Agent App path as the user. */
export async function openFrameworkSettings(page: Page, name: string) {
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await page.getByRole('main').getByRole('button', { name: 'Agent App', exact: true }).click()
  const card = page.getByRole('article', { name: `${name} settings`, exact: true })
  await expect(card).toBeVisible()
  const header = card.locator('[role="button"][aria-expanded]').first()
  if (await header.getAttribute('aria-expanded') === 'false') await header.click()
  return card
}
