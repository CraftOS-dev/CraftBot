import { test, expect, type Page } from '@playwright/test'

async function response(page: Page, data: Record<string, unknown>, type = 'agent_app_trigger_consent') {
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  if (type === 'agent_app_trigger_consent' && !('requestId' in data)) {
    const sent = await requests(page)
    data = { ...data, requestId: sent.filter(request => request.data.projectId === data.projectId).at(-1)?.data.requestId }
  }
  await page.evaluate(({ type, data }) => {
    window.dispatchEvent(new CustomEvent('fixture-response', { detail: { type, data } }))
  }, { type, data })
}

async function requests(page: Page) {
  return page.evaluate(() => (window as typeof window & {
    consentRequests: Array<{ type: string; data: Record<string, unknown> }>
  }).consentRequests.filter(request => request.type === 'agent_app_trigger_consent'))
}

// The title is shared; the app asking is named in the dialog's own heading.
function reviewOf(page: Page, app: string) {
  return page.getByRole('dialog', { name: 'Agent App requesting access to CraftBot' })
    .filter({ has: page.getByRole('heading', { name: app, exact: true }) })
}

const reviewed = {
  revision: 'review-v1', required: false, needsReview: false,
  triggers: [{ name: 'summarize', description: 'Summarize a recording', instruction: 'Prepare a summary.', change: 'approved' }],
}

const approvalMessage = 'Requests are now allowed. Try the action again.'

test('approval confirmation describes saved permission without claiming app readiness', async ({ page }, testInfo) => {
  await page.goto('/tests/trigger-consent.html')
  await page.getByRole('button', { name: 'Allow', exact: true }).click()
  await expect(page.getByText(approvalMessage, { exact: true })).toHaveCount(0)
  await response(page, { projectId: 'notes', success: true, consent: reviewed })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const confirmation = page.getByRole('status').filter({ hasText: approvalMessage })
  await expect(confirmation).toBeVisible()
  await expect(confirmation).not.toContainText('Everything is ready')
  await expect(confirmation).toHaveCSS('transform', 'none')
  await page.screenshot({ path: testInfo.outputPath('approval-confirmation.png') })
  // A duplicate response must not produce another confirmation.
  await response(page, { projectId: 'notes', success: true, consent: reviewed })
  await expect(page.getByText(approvalMessage, { exact: true })).toHaveCount(1)
})

for (const outcome of ['unrelated', 'failed', 'denied', 'disconnected']) {
  test(`approval confirmation is not shown for a ${outcome} decision`, async ({ page }) => {
    await page.goto('/tests/trigger-consent.html')
    await page.getByRole('button', { name: outcome === 'denied' ? "Don't allow" : 'Allow', exact: true }).click()
    if (outcome === 'disconnected') {
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-connected', { detail: false })))
    }
    await response(page, { projectId: 'notes', success: outcome !== 'failed',
      ...(outcome === 'unrelated' ? { requestId: 'another-client' } : {}),
      ...(outcome === 'failed' ? { error: 'Could not save permission.' } : {}),
      consent: outcome === 'denied' ? { ...reviewed, triggers: [] } : reviewed,
    })
    await expect(page.getByText(approvalMessage, { exact: true })).toHaveCount(0)
  })
}

for (const width of [1280, 390]) {
  test(`review lists plain-language requests only, before approval and after a change at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/tests/trigger-consent.html?no-requests')
    const trigger = {
      name: 'email_summary', description: 'Email a summary', instruction: 'Run `agent-app run notes summary.email --to <recipient>`.', change: 'new',
      params: { recipient: { type: 'string', description: 'Who receives the summary', required: true, default: 'original@example.test' } },
    }
    const consent = { revision: 'params-v1', required: true, needsReview: true, triggers: [trigger] }
    await response(page, { projectId: 'notes', triggerConsent: consent }, 'agent_app_ready')
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('listitem')).toHaveText(['Email a summary'])
    // Agent instructions and input specs are for the agent, never the person.
    for (const hidden of ['agent-app', 'recipient', 'Who receives the summary', 'original@example.test']) {
      await expect(dialog).not.toContainText(hidden)
    }
    await expect(dialog.locator('details, summary, code, pre')).toHaveCount(0)
    await expect(dialog.getByText('New', { exact: true })).toHaveCount(0)
    await dialog.getByRole('button', { name: 'Allow', exact: true }).click()
    expect((await requests(page))[0].data.revision).toBe('params-v1')
    await response(page, { projectId: 'notes', success: true,
      consent: { ...consent, required: false, needsReview: false, triggers: [{ ...trigger, change: 'approved' }] } })
    await expect(dialog).toHaveCount(0)

    await response(page, { projectId: 'notes', triggerConsent: { ...consent, revision: 'params-v2',
      triggers: [{ ...trigger, change: 'changed', params: { recipient: { ...trigger.params.recipient, default: 'changed@example.test' } } }] } }, 'agent_app_ready')
    await expect(dialog.getByText('Changed', { exact: true })).toBeVisible()
    await expect(dialog).not.toContainText('changed@example.test')
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    await expect(dialog.getByRole('button', { name: 'Allow', exact: true })).toBeInViewport()
    await expect(dialog.locator('..')).toHaveCSS('opacity', '1')
    const screenshot = testInfo.outputPath('changed-request.png')
    await page.screenshot({ path: screenshot })
    await testInfo.attach('Changed request', { path: screenshot, contentType: 'image/png' })
    await dialog.getByRole('button', { name: 'Allow', exact: true }).click()
    expect((await requests(page))[1].data.revision).toBe('params-v2')
  })
}

test('status badges appear only when an update mixes allowed and new requests', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByRole('dialog').getByText('New', { exact: true })).toHaveCount(0)
  await response(page, { projectId: 'notes', triggerConsent: { revision: 'mixed-v1', required: true, needsReview: true, triggers: [
    { name: 'summarize', description: 'Summarize a recording', instruction: 'Prepare a summary.', change: 'approved' },
    { name: 'email', description: 'Email the summary', instruction: 'Send the summary by email.', change: 'changed' },
    { name: 'tag', description: 'Tag speakers', instruction: 'Tag each speaker.', change: 'new' },
  ] } }, 'agent_app_ready')
  const dialog = page.getByRole('dialog')
  for (const label of ['Allowed', 'Changed', 'New']) await expect(dialog.getByText(label, { exact: true })).toBeVisible()
})

test('the review shows three requests and the rest behind a counted See more', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?no-requests')
  const triggers = ['One', 'Two', 'Three', 'Four', 'Five'].map(name => ({ name, description: `Request ${name}`, instruction: 'x', change: 'new' }))
  await response(page, { projectId: 'notes', triggerConsent: { revision: 'five', required: true, needsReview: true, triggers } }, 'agent_app_ready')
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('listitem')).toHaveText(['Request One', 'Request Two', 'Request Three'])
  const seeMore = dialog.getByRole('button', { name: 'See more (2)', exact: true })
  await expect(seeMore).toHaveCSS('text-decoration-line', 'underline')
  await expect(seeMore).toHaveCSS('cursor', 'pointer')
  await seeMore.click()
  await expect(dialog.getByRole('listitem')).toHaveText(['Request One', 'Request Two', 'Request Three', 'Request Four', 'Request Five'])
  await expect(dialog.getByRole('button', { name: /See more/ })).toHaveCount(0)

  // In an update, requests that still need a choice come first, so the
  // collapsed list never hides them.
  await response(page, { projectId: 'notes', triggerConsent: { revision: 'update', required: true, needsReview: true, triggers: [
    ...['A', 'B', 'C'].map(name => ({ name, description: `Kept ${name}`, instruction: 'x', change: 'approved' })),
    { name: 'D', description: 'Changed D', instruction: 'x', change: 'changed' },
    { name: 'E', description: 'New E', instruction: 'x', change: 'new' },
  ] } }, 'agent_app_ready')
  await expect(dialog.getByRole('listitem')).toHaveText(['Changed DChanged', 'New ENew', 'Kept AAllowed'])
  await expect(dialog.getByRole('button', { name: 'See more (2)', exact: true })).toBeVisible()
})

test('first launch shows request review before any trigger fires; explicit allowance carries its revision', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await expect(reviewOf(page, 'Audio Notes')).toBeVisible()
  await expect(page.getByText('Summarize a recording', { exact: true })).toBeVisible()
  expect(await requests(page)).toEqual([])
  await expect(page.getByRole('dialog')).not.toContainText('Read the selected recording and prepare a summary.')
  await page.getByRole('button', { name: 'Allow', exact: true }).click()
  expect(await requests(page)).toEqual([{ type: 'agent_app_trigger_consent', data: { projectId: 'notes', revision: 'review-v1', allow: true, requestId: expect.any(String) } }])
  await expect(page.getByRole('button', { name: "Don't allow" })).toBeDisabled()
  await response(page, { projectId: 'notes', success: true, consent: reviewed })
  await expect(reviewOf(page, 'Audio Notes')).toHaveCount(0)
})

test('approval correlation works when randomUUID is unavailable on an HTTP origin', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(crypto, 'randomUUID', { value: undefined }))
  await page.goto('/tests/trigger-consent.html')
  await page.getByRole('button', { name: 'Allow', exact: true }).click()
  expect((await requests(page))[0].data.requestId).toBeTruthy()
  await response(page, { projectId: 'notes', success: true, consent: reviewed })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('declining keeps requests off and reopening remains available without repeated prompts', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await page.getByRole('button', { name: "Don't allow" }).click()
  expect((await requests(page))[0].data.allow).toBe(false)
  const declined = { ...reviewed, required: true }
  await response(page, { projectId: 'notes', success: true, consent: declined })
  await expect(reviewOf(page, 'Audio Notes')).toHaveCount(0)
  await response(page, { projectId: 'notes', url: 'http://localhost:3189', port: 3189, triggerConsent: declined }, 'agent_app_ready')
  await expect(reviewOf(page, 'Audio Notes')).toHaveCount(0)
  await page.getByRole('button', { name: 'Review requests again' }).click()
  await expect(reviewOf(page, 'Audio Notes')).toBeVisible()
})

test('stale approval refreshes the list and requires another click for the changed revision', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await page.getByRole('button', { name: 'Allow', exact: true }).click()
  await response(page, {
    projectId: 'notes', success: false, error: 'The app requests changed. Review them again.',
    consent: { ...reviewed, revision: 'review-v2', required: true, needsReview: true,
      triggers: [{ name: 'summarize', description: 'Email the summary', instruction: 'Send the summary by email.', change: 'changed' }] },
  })
  await expect(page.getByRole('alert')).toContainText('changed')
  await expect(page.getByText('Email the summary', { exact: true })).toBeVisible()
  expect(await requests(page)).toHaveLength(1)
  await page.getByRole('button', { name: 'Allow', exact: true }).click()
  expect((await requests(page))[1].data.revision).toBe('review-v2')
})

test('unchanged approved launch stays quiet; changed definitions open the modal again', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?no-requests')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await expect(reviewOf(page, 'Audio Notes')).toHaveCount(0)
  await response(page, { projectId: 'notes', url: 'http://localhost:3189', port: 3189, triggerConsent: reviewed }, 'agent_app_ready')
  await expect(reviewOf(page, 'Audio Notes')).toHaveCount(0)
  await response(page, { projectId: 'notes', url: 'http://localhost:3189', port: 3189, triggerConsent: { ...reviewed, revision: 'review-v2', required: true, needsReview: true } }, 'agent_app_ready')
  await expect(reviewOf(page, 'Audio Notes')).toBeVisible()
})

test('disconnect keeps pending review visible and prevents approval until reconnect', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByText('The app is running in the background.')).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-connected', { detail: false })))
  await expect(page.getByRole('button', { name: 'Allow', exact: true })).toBeDisabled()
  await expect(page.getByRole('alert')).toContainText('Connection lost')
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-connected', { detail: true })))
  await expect(page.getByRole('button', { name: 'Allow', exact: true })).toBeEnabled()
  expect(await requests(page)).toHaveLength(0)
})

test('review has modal semantics, contains keyboard focus and restores its opener', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?no-requests')
  const opener = page.getByRole('button', { name: 'Review requests again' })
  await opener.focus()
  await response(page, { projectId: 'notes', triggerConsent: { ...reviewed, required: true, needsReview: true } }, 'agent_app_ready')
  const dialog = reviewOf(page, 'Audio Notes')
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  await expect(dialog).toBeFocused()
  // Focus is contained on the dialog itself, which never draws a ring.
  await expect(dialog).toHaveCSS('outline-style', 'none')
  await expect(page.locator('#root')).toHaveAttribute('inert', '')
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(dialog.getByRole('button', { name: 'Allow', exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeFocused()
  // Only the X closes the review, and closing it means "Don't allow".
  await page.keyboard.press('Escape')
  await page.mouse.click(5, 5)
  await expect(dialog).toBeVisible()
  expect(await requests(page)).toEqual([])
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  expect((await requests(page)).map(request => request.data.allow)).toEqual([false])
  await response(page, { projectId: 'notes', success: true, consent: { ...reviewed, required: true } })
  await expect(dialog).toHaveCount(0)
  await expect(opener).toBeFocused()
  await expect(page.locator('#root')).not.toHaveAttribute('inert', '')
})

for (const outside of ['Escape', 'backdrop']) {
  test(`${outside} leaves an approved review open without a decision`, async ({ page }) => {
    await page.goto('/tests/trigger-consent.html?no-requests')
    await response(page, { projectId: 'notes', triggerConsent: reviewed }, 'agent_app_ready')
    await page.getByRole('button', { name: 'Review requests again' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Allowed', { exact: true })).toBeVisible()
    if (outside === 'Escape') await page.keyboard.press('Escape')
    else await page.mouse.click(5, 5)
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('Allowed', { exact: true })).toBeVisible()
    expect(await requests(page)).toEqual([])
  })
}

test('closing a first review declines it; refreshes stay quiet and a new revision prompts', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  expect((await requests(page)).map(request => request.data)).toEqual([
    { projectId: 'notes', revision: 'review-v1', allow: false, requestId: expect.any(String) },
  ])
  await expect(page.getByRole('dialog')).toBeVisible()
  const declined = { ...reviewed, required: true, needsReview: false, triggers: [{ ...reviewed.triggers[0], change: 'new' }] }
  await response(page, { projectId: 'notes', success: true, consent: declined })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await response(page, { projectId: 'notes', triggerConsent: declined }, 'agent_app_ready')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await response(page, { projectId: 'notes', triggerConsent: { ...declined, revision: 'review-v2', needsReview: true } }, 'agent_app_ready')
  await expect(page.getByRole('dialog')).toBeVisible()
})

test('closing queued reviews declines each app in turn', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?two-apps&queued-apps')
  const first = reviewOf(page, 'Audio Notes')
  await expect(first).toBeVisible()
  await first.getByRole('button', { name: 'Close', exact: true }).click()
  await response(page, { projectId: 'notes', success: true, consent: { ...reviewed, required: true } })
  const next = reviewOf(page, 'Calendar')
  await expect(next).toBeFocused()
  await next.getByRole('button', { name: 'Close', exact: true }).click()
  await response(page, { projectId: 'calendar', success: true, consent: { ...reviewed, revision: 'calendar-v1', required: true } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect((await requests(page)).map(request => [request.data.projectId, request.data.allow]))
    .toEqual([['notes', false], ['calendar', false]])
})

test('closing while offline leaves without a decision, since nothing can be saved', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-connected', { detail: false })))
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(await requests(page)).toEqual([])
})

test('explicitly keeping an approved app off still revokes its permissions', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?no-requests')
  await response(page, { projectId: 'notes', triggerConsent: reviewed }, 'agent_app_ready')
  await page.getByRole('button', { name: 'Review requests again' }).click()
  await page.getByRole('button', { name: "Don't allow" }).click()
  expect((await requests(page))[0].data.allow).toBe(false)
  await response(page, { projectId: 'notes', success: true, consent: { ...reviewed, required: true,
    triggers: [{ ...reviewed.triggers[0], change: 'new' }] } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Review requests again' }).click()
  // Revoked requests read as a fresh first review: listed, no Allowed badge.
  await expect(page.getByRole('dialog').getByText('Summarize a recording', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog').getByText('Allowed', { exact: true })).toHaveCount(0)
})

test('failed consent save can be dismissed without a second write or renewed prompt', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html')
  await page.getByRole('button', { name: "Don't allow" }).click()
  await response(page, { projectId: 'notes', success: false, error: 'Could not save: access denied.',
    consent: { ...reviewed, required: true, needsReview: true, triggers: [{ ...reviewed.triggers[0], change: 'new' }] } })
  await expect(page.getByRole('alert')).toContainText('access denied')
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(await requests(page)).toHaveLength(1)
  await response(page, { projectId: 'notes', triggerConsent: { ...reviewed, required: true, needsReview: true } }, 'agent_app_ready')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Review requests again' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: "Don't allow" }).click()
  expect(await requests(page)).toHaveLength(2)
  await response(page, { projectId: 'notes', success: true, consent: { ...reviewed, required: true } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

const unreadableConsent = { revision: '', required: true, needsReview: false, triggers: [],
  error: "This app's agent requests could not be read." }

test('keeping requests off saves revocation despite a read error and repair requires fresh approval', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?no-requests')
  await response(page, { projectId: 'notes', triggerConsent: reviewed }, 'agent_app_ready')
  await response(page, { projectId: 'notes', triggerConsent: unreadableConsent }, 'agent_app_ready')
  await page.getByRole('button', { name: 'Review requests again' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('alert')).toContainText('could not be read')
  await expect(dialog.getByRole('button', { name: 'Allow', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: "Don't allow" }).click()
  expect((await requests(page))[0].data).toEqual({ projectId: 'notes', revision: '', allow: false, requestId: expect.any(String) })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeDisabled()
  await response(page, { projectId: 'notes', success: true, consent: unreadableConsent })
  await expect(dialog).toHaveCount(0)
  await response(page, { projectId: 'notes', triggerConsent: { ...reviewed, required: true, needsReview: true,
    triggers: [{ ...reviewed.triggers[0], change: 'new' }] } }, 'agent_app_ready')
  await expect(dialog.getByText('Summarize a recording', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Allowed', { exact: true })).toHaveCount(0)
  expect(await requests(page)).toHaveLength(1)
})

test('a failed revocation with unreadable definitions shows the save error and can retry', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?no-requests')
  await response(page, { projectId: 'notes', triggerConsent: unreadableConsent }, 'agent_app_ready')
  await page.getByRole('button', { name: 'Review requests again' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: "Don't allow" }).click()
  expect(await requests(page)).toHaveLength(1)
  await response(page, { projectId: 'notes', success: false, error: 'Consent storage is read-only', consent: unreadableConsent })
  await expect(dialog.getByRole('alert')).toContainText('read-only')
  await expect(dialog.getByRole('button', { name: 'Allow', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: "Don't allow" }).click()
  expect(await requests(page)).toHaveLength(2)
  await response(page, { projectId: 'notes', success: true, consent: unreadableConsent })
  await expect(dialog).toHaveCount(0)
})

test('unrelated client responses update grants without closing or poisoning the current review', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?two-apps&no-requests')
  await page.getByRole('button', { name: 'Review requests again' }).click()
  const dialog = reviewOf(page, 'Audio Notes')
  await response(page, { projectId: 'calendar', requestId: 'another-client', success: true, consent: reviewed })
  await expect(dialog).toBeVisible()
  await response(page, { projectId: 'notes', requestId: 'another-client', success: true, consent: reviewed })
  await expect(dialog.getByText('Allowed', { exact: true })).toBeVisible()
  await response(page, { projectId: 'calendar', requestId: 'another-client', success: false, error: 'Foreign error' })
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await response(page, { projectId: 'notes', success: true, consent: { ...reviewed, required: true } })
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: 'Review other app' }).click()
  await expect(reviewOf(page, 'Calendar').getByText('Allowed', { exact: true })).toBeVisible()
})

test('only the matching request settles a pending choice, including another client on the same app', async ({ page }) => {
  await page.goto('/tests/trigger-consent.html?two-apps')
  const dialog = reviewOf(page, 'Audio Notes')
  await dialog.getByRole('button', { name: 'Allow', exact: true }).click()
  const allow = dialog.getByRole('button', { name: 'Allow', exact: true })
  for (const projectId of ['calendar', 'notes']) {
    await response(page, { projectId, requestId: 'another-client', success: true, consent: reviewed })
    await expect(dialog).toBeVisible()
    await expect(allow).toBeDisabled()
    await response(page, { projectId, requestId: 'another-client', success: false, error: 'Foreign error' })
    await expect(dialog.getByRole('alert')).toHaveCount(0)
    await expect(allow).toBeDisabled()
  }
  await response(page, { projectId: 'notes', requestId: null, success: true, consent: reviewed })
  await expect(allow).toBeDisabled()
  await response(page, { projectId: 'notes', success: false, error: 'Our save failed.', consent: reviewed })
  await expect(dialog.getByRole('alert')).toContainText('Our save failed')
  await response(page, { projectId: 'calendar', requestId: 'another-client', success: true, consent: reviewed })
  await expect(dialog.getByRole('alert')).toContainText('Our save failed')
  await allow.click()
  const sent = await requests(page)
  expect(sent[0].data.requestId).not.toBe(sent[1].data.requestId)
  await response(page, { projectId: 'notes', requestId: sent[0].data.requestId, success: true, consent: reviewed })
  await expect(allow).toBeDisabled()
  await response(page, { projectId: 'notes', success: true, consent: reviewed })
  await expect(dialog).toHaveCount(0)
})

for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
  test(`30 requests scroll to the last one with fixed actions at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto('/tests/trigger-consent.html?many-requests')
    const dialog = page.getByRole('dialog')
    const list = dialog.getByRole('list')
    await expect(list.getByRole('listitem')).toHaveCount(3)
    await dialog.getByRole('button', { name: 'See more (27)', exact: true }).click()
    await expect(list.getByRole('listitem')).toHaveCount(30)
    // The dialog body scrolls; header and actions stay put.
    expect(await list.evaluate(el => { const body = el.parentElement!; return body.scrollHeight > body.clientHeight && getComputedStyle(body).overflowY === 'auto' })).toBe(true)
    const last = list.getByRole('listitem').last()
    await last.scrollIntoViewIfNeeded()
    await expect(last).toBeInViewport()
    await expect(last).toHaveText('QA request 30')
    const allow = dialog.getByRole('button', { name: 'Allow', exact: true })
    const decline = dialog.getByRole('button', { name: "Don't allow" })
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

test('Settings can stop or allow an app\'s requests any time after the first review', async ({ page }, testInfo) => {
  await page.goto('/tests/trigger-consent.html?settings')
  await page.getByRole('button', { name: /Audio Notes/ }).first().click()
  const toggle = page.getByRole('checkbox', { name: 'Allow requests to CraftBot', exact: true })
  await expect(toggle).toBeChecked()
  // The switch is the setting; the list stays folded until asked for.
  await expect(page.getByText('Summarize a recording', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'View requests (1)', exact: true }).click()
  await expect(page.getByText('Summarize a recording', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('settings-requests.png') })
  await page.getByRole('button', { name: 'Hide requests', exact: true }).click()
  await expect(page.getByText('Summarize a recording', { exact: true })).toHaveCount(0)

  await toggle.click()
  expect((await requests(page)).map(request => request.data)).toEqual([
    { projectId: 'notes', revision: 'review-v1', allow: false, requestId: expect.any(String) },
  ])
  await expect(toggle).toBeDisabled()
  const stopped = { ...reviewed, required: true, triggers: [{ ...reviewed.triggers[0], change: 'new' }] }
  await response(page, { projectId: 'notes', success: true, consent: stopped })
  await expect(toggle).not.toBeChecked()
  await expect(toggle).toBeEnabled()
  // A Settings decision never opens the review dialog.
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await toggle.click()
  expect((await requests(page))[1].data).toMatchObject({ projectId: 'notes', revision: 'review-v1', allow: true })
  await response(page, { projectId: 'notes', success: false, error: 'Could not save permission.', consent: stopped })
  await expect(page.getByRole('alert')).toContainText('Could not save permission.')
  await expect(toggle).not.toBeChecked()
  await toggle.click()
  await response(page, { projectId: 'notes', success: true, consent: reviewed })
  await expect(toggle).toBeChecked()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
