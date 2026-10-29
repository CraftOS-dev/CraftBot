import { test, expect, type Page } from '@playwright/test'

async function response(page: Page, data: Record<string, unknown>, type = 'agent_app_trigger_consent') {
  await page.evaluate(({ type, data }) => {
    window.dispatchEvent(new CustomEvent('fixture-response', { detail: { type, data } }))
  }, { type, data })
}

async function requests(page: Page) {
  return page.evaluate(() => (window as typeof window & {
    consentRequests: Array<{ type: string; data: Record<string, unknown> }>
  }).consentRequests.filter(request => request.type === 'agent_app_trigger_consent'))
}

const reviewed = {
  revision: 'review-v1', required: false, needsReview: false,
  triggers: [{ name: 'summarize', description: 'Summarize a recording', instruction: 'Prepare a summary.', change: 'approved' }],
}

test('first launch shows request review before any trigger fires; explicit allowance carries its revision', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await expect(page.getByText('Allow requests from Audio Notes?')).toBeVisible()
  await expect(page.getByText('Summarize a recording', { exact: true })).toBeVisible()
  expect(await requests(page)).toEqual([])
  await page.getByText('View instructions for CraftBot').click()
  await expect(page.getByText('Read the selected recording and prepare a summary.')).toBeVisible()
  await page.getByRole('button', { name: 'Allow requests', exact: true }).click()
  expect(await requests(page)).toEqual([{ type: 'agent_app_trigger_consent', data: { projectId: 'notes', revision: 'review-v1', allow: true } }])
  await expect(page.getByRole('button', { name: 'Keep requests off' })).toBeDisabled()
  await response(page, { projectId: 'notes', success: true, consent: reviewed })
  await expect(page.getByText('Allow requests from Audio Notes?')).toHaveCount(0)
})

test('declining keeps requests off and reopening remains available without repeated prompts', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await page.getByRole('button', { name: 'Keep requests off' }).click()
  expect((await requests(page))[0].data.allow).toBe(false)
  const declined = { ...reviewed, required: true }
  await response(page, { projectId: 'notes', success: true, consent: declined })
  await expect(page.getByText('Allow requests from Audio Notes?')).toHaveCount(0)
  await response(page, { projectId: 'notes', url: 'http://localhost:3189', port: 3189, triggerConsent: declined }, 'agent_app_ready')
  await expect(page.getByText('Allow requests from Audio Notes?')).toHaveCount(0)
  await page.getByRole('button', { name: 'Review requests again' }).click()
  await expect(page.getByText('Allow requests from Audio Notes?')).toBeVisible()
})

test('stale approval refreshes the list and requires another click for the changed revision', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await page.getByRole('button', { name: 'Allow requests', exact: true }).click()
  await response(page, {
    projectId: 'notes', success: false, error: 'The app requests changed. Review them again.',
    consent: { ...reviewed, revision: 'review-v2', required: true, needsReview: true,
      triggers: [{ name: 'summarize', description: 'Email the summary', instruction: 'Send the summary by email.', change: 'changed' }] },
  })
  await expect(page.getByRole('alert')).toContainText('changed')
  await expect(page.getByText('Email the summary', { exact: true })).toBeVisible()
  expect(await requests(page)).toHaveLength(1)
  await page.getByRole('button', { name: 'Allow requests', exact: true }).click()
  expect((await requests(page))[1].data.revision).toBe('review-v2')
})

test('unchanged approved launch stays quiet; changed definitions open the modal again', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?no-requests')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await expect(page.getByText('Allow requests from Audio Notes?')).toHaveCount(0)
  await response(page, { projectId: 'notes', url: 'http://localhost:3189', port: 3189, triggerConsent: reviewed }, 'agent_app_ready')
  await expect(page.getByText('Allow requests from Audio Notes?')).toHaveCount(0)
  await response(page, { projectId: 'notes', url: 'http://localhost:3189', port: 3189, triggerConsent: { ...reviewed, revision: 'review-v2', required: true, needsReview: true } }, 'agent_app_ready')
  await expect(page.getByText('Allow requests from Audio Notes?')).toBeVisible()
})

test('disconnect keeps pending review visible and prevents approval until reconnect', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-connected', { detail: false })))
  await expect(page.getByRole('button', { name: 'Allow requests', exact: true })).toBeDisabled()
  await expect(page.getByRole('alert')).toContainText('Connection lost')
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-connected', { detail: true })))
  await expect(page.getByRole('button', { name: 'Allow requests', exact: true })).toBeEnabled()
  expect(await requests(page)).toHaveLength(0)
})

test('review has modal semantics, contains keyboard focus and restores its opener', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?no-requests')
  const opener = page.getByRole('button', { name: 'Review requests again' })
  await opener.focus()
  await response(page, { projectId: 'notes', triggerConsent: { ...reviewed, required: true, needsReview: true } }, 'agent_app_ready')
  const dialog = page.getByRole('dialog', { name: 'Allow requests from Audio Notes?' })
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  await expect(dialog).toBeFocused()
  await expect(page.locator('#root')).toHaveAttribute('inert', '')
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(dialog.getByRole('button', { name: 'Allow requests', exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  expect((await requests(page))[0].data.allow).toBe(false)
  await response(page, { projectId: 'notes', success: true, consent: { ...reviewed, required: true } })
  await expect(dialog).toHaveCount(0)
  await expect(opener).toBeFocused()
  await expect(page.locator('#root')).not.toHaveAttribute('inert', '')
})

for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
  test(`30 requests scroll with reachable final instructions and fixed actions at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto('/tests/trigger-consent.html?many-requests')
    const dialog = page.getByRole('dialog')
    const list = dialog.getByRole('list')
    await expect(list.getByRole('listitem')).toHaveCount(30)
    expect(await list.evaluate(el => el.scrollHeight > el.clientHeight && getComputedStyle(el).overflowY === 'auto')).toBe(true)
    const last = list.getByRole('listitem').last()
    await last.scrollIntoViewIfNeeded()
    await last.locator('summary').click()
    await expect(last.getByText('Instructions for request 30.', { exact: false })).toBeVisible()
    const allow = dialog.getByRole('button', { name: 'Allow requests', exact: true })
    const decline = dialog.getByRole('button', { name: 'Keep requests off' })
    await expect(allow).toBeInViewport()
    await expect(decline).toBeInViewport()
    const bounds = await dialog.boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width)
    await allow.click()
    expect((await requests(page))[0].data.allow).toBe(true)
  })
}

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
