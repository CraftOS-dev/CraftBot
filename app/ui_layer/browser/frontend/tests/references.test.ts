import { test, expect, type Page } from '@playwright/test'

const input = (page: Page) => page.locator('textarea')
async function requests(page: Page) {
  return page.evaluate(() => (window as unknown as { referenceRequests: Record<string, unknown>[] }).referenceRequests.filter(r => r.type === 'message'))
}
async function respond(page: Page, type: string, data: unknown) {
  await page.evaluate(({ type, data }) => window.dispatchEvent(new CustomEvent('fixture-response', { detail: { type, data } })), { type, data })
}

test('typing @ searches both source types and selection attaches without sending', async ({ page }) => {
  await page.goto('/tests/references.html')
  await input(page).fill('@')
  await expect(page.getByRole('option', { name: /Pricing discussion/ })).toBeVisible()
  await expect(page.getByRole('option', { name: /Weather dashboard/ })).toHaveCount(1)
  await expect(page.getByRole('option', { name: /Current session/ })).toHaveCount(0)
  await input(page).fill('Compare @pric')
  await expect(page.getByRole('option')).toHaveCount(1)
  await input(page).press('Enter')
  await expect(input(page)).toHaveValue('Compare ')
  await expect(page.getByRole('button', { name: 'Pricing discussion', exact: true })).toBeVisible()
  expect(await requests(page)).toHaveLength(0)
  await input(page).press('Enter')
  await expect.poll(() => requests(page)).toHaveLength(1)
  expect((await requests(page))[0].references).toEqual([{ kind: 'session', targetId: 'pricing' }])
})

test('email, a bare @ and an escaped mention preserve ordinary input', async ({ page }) => {
  await page.goto('/tests/references.html')
  await input(page).fill('name@example.com')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await input(page).fill('see you @ 5pm')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await input(page).fill('@does-not-exist')
  await expect(page.getByText('No matches')).toBeVisible()
  await input(page).press('Escape')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  // Typing on does not reopen a mention the user dismissed.
  await input(page).pressSequentially('-really')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  expect(await requests(page)).toHaveLength(0)
  await input(page).press('Enter')
  await expect.poll(() => requests(page)).toHaveLength(1)
  expect((await requests(page))[0].content).toBe('@does-not-exist-really')
})

test('a mention that matches nothing never blocks Enter', async ({ page }) => {
  await page.goto('/tests/references.html')
  await input(page).fill('@nobody')
  await expect(page.getByText('No matches')).toBeVisible()
  await input(page).press('Enter')
  await expect.poll(() => requests(page)).toHaveLength(1)
  expect((await requests(page))[0].content).toBe('@nobody')
  // Prose after an unmatched mention closes the list instead of waiting for Escape.
  await input(page).fill('ping @john please review')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await input(page).press('Enter')
  await expect.poll(() => requests(page)).toHaveLength(2)
  expect((await requests(page))[1].content).toBe('ping @john please review')
})

test('+ picker shares selections with @ and supports reference-only sends', async ({ page }) => {
  await page.goto('/tests/references.html')
  await page.getByRole('button', { name: 'Attach and tools' }).click()
  await page.getByRole('button', { name: 'Add context', exact: true }).hover()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('textbox').fill('Weather dashboard')
  await expect(dialog.getByRole('button', { name: /Weather dashboard/ })).toHaveCount(1)
  await page.screenshot({ path: 'test-results/references-picker.png', animations: 'disabled' })
  await dialog.getByRole('button', { name: /Weather dashboard/ }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add context', exact: true })).toHaveCount(0)
  await expect(input(page)).toBeFocused()
  await input(page).fill('@weather')
  await input(page).press('Tab')
  await expect(page.getByRole('button', { name: 'Weather dashboard', exact: true })).toHaveCount(1)
  await expect(input(page)).toHaveValue('')
  await input(page).press('Enter')
  expect((await requests(page))[0].references).toEqual([{ kind: 'agent_app', targetId: 'weather' }])
})

test('server echo and history reload retain the captured preview', async ({ page }) => {
  await page.goto('/tests/references.html')
  await input(page).fill('@pricing')
  await input(page).press('Enter')
  await input(page).press('Enter')
  const sent = (await requests(page))[0]
  const message = { sender: 'You', content: 'Referenced: Pricing discussion', style: 'user', timestamp: 1,
    sessionId: 'dest', messageId: 'server-message', clientId: sent.clientId,
    references: [{ kind: 'session', targetId: 'pricing', label: 'Pricing discussion', capturedAt: '2026-10-26T12:00:00Z', schemaVersion: 1, contentHash: 'test', excerpt: 'Original captured decision', truncated: true }] }
  await respond(page, 'chat_message', message)
  await expect(page.getByText('Referenced: Pricing discussion', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Pricing discussion', exact: true }).click()
  await expect(page.getByText('Original captured decision', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.evaluate(message => sessionStorage.setItem('reference-fixture-history', JSON.stringify([message])), message)
  await page.reload()
  await page.getByRole('button', { name: 'Pricing discussion', exact: true }).click()
  await expect(page.getByText('Original captured decision', { exact: true })).toBeVisible()
})

test('failed submissions expose an explicit retry', async ({ page }) => {
  await page.goto('/tests/references.html')
  await input(page).fill('@pricing')
  await input(page).press('Enter')
  await input(page).press('Enter')
  const sent = (await requests(page))[0]
  await respond(page, 'message_rejected', { sessionId: 'dest', clientId: sent.clientId, error: 'Source unavailable' })
  await page.getByRole('button', { name: 'Retry message' }).click()
  await expect.poll(() => requests(page)).toHaveLength(2)
  expect((await requests(page))[1]).toEqual(sent)
})

test('a failed reference can be restored, removed and resubmitted', async ({ page }) => {
  await page.goto('/tests/references.html')
  await input(page).fill('Compare @pricing')
  await input(page).press('Enter')
  await input(page).press('Enter')
  const sent = (await requests(page))[0]
  await respond(page, 'message_rejected', { sessionId: 'dest', clientId: sent.clientId, error: 'Source unavailable' })
  await page.getByRole('button', { name: 'Edit message', exact: true }).click()
  await expect(input(page)).toHaveValue('Compare')
  await page.getByRole('button', { name: 'Remove reference: Pricing discussion' }).click()
  await input(page).press('Enter')
  expect((await requests(page))[1].references).toEqual([])
})

test('caret selection preserves surrounding text and mixed attachments', async ({ page }) => {
  await page.goto('/tests/references.html')
  await input(page).fill('Compare @pricing tomorrow')
  for (let i = 0; i < 9; i++) await input(page).press('ArrowLeft')
  await expect(page.getByRole('option', { name: /Pricing discussion/ })).toBeVisible()
  await input(page).press('Enter')
  await expect(input(page)).toHaveValue('Compare  tomorrow')
  await page.locator('input[type=file][multiple]').setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('hello') })
  await expect(page.getByText('notes.txt', { exact: true })).toBeVisible()
  await input(page).fill('/compare this')
  await input(page).press('Enter')
  const sent = (await requests(page))[0]
  expect(sent.type).toBe('message')
  expect(sent.content).toBe('/compare this')
  expect(sent.references).toEqual([{ kind: 'session', targetId: 'pricing' }])
  expect(sent.attachments).toEqual([expect.objectContaining({ name: 'notes.txt' })])
})

test('rejecting a mid-run reference preserves the active run controls', async ({ page }) => {
  await page.goto('/tests/references.html')
  await expect(input(page)).toBeVisible()
  await respond(page, 'session_busy', { sessionId: 'dest', state: 'running', busy: true })
  await expect(page.getByRole('button', { name: 'Stop run' })).toBeVisible()
  await input(page).fill('@pricing')
  await input(page).press('Enter')
  await input(page).press('Enter')
  const sent = (await requests(page))[0]
  await respond(page, 'message_rejected', { sessionId: 'dest', clientId: sent.clientId, error: 'Source unavailable' })
  await expect(page.getByRole('button', { name: 'Stop run' })).toBeVisible()
})
