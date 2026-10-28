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
