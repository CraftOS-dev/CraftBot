import { test, expect, type Page } from '@playwright/test'

async function response(page: Page, type: string, data: Record<string, unknown>) {
  await page.evaluate(({ type, data }) => {
    window.dispatchEvent(new CustomEvent('fixture-response', { detail: { type, data } }))
  }, { type, data })
}

async function sent(page: Page, type: string) {
  return page.evaluate(type => {
    const requests = (window as typeof window & {
      subscriptionRequests: Array<{ type: string; data: Record<string, unknown> }>
    }).subscriptionRequests
    return requests.filter(request => request.type === type)
  }, type)
}

for (const screen of ['settings', 'onboarding']) {
  test(`${screen}: invalid login retains disconnect after failure and clears after verified logout`, async ({ page }) => {
    await page.goto(`/tests/subscription-recovery.html?screen=${screen}`)
    await expect(page.getByRole('button', { name: 'Sign in with Claude', exact: true })).toBeVisible()
    await expect(page.getByRole('alert')).toContainText('Claude login needs recovery.')
    const disconnect = page.getByRole('button', { name: 'Disconnect', exact: true })
    await disconnect.click()
    expect(await sent(page, 'model_subscription_disconnect')).toEqual([
      { type: 'model_subscription_disconnect', data: { provider: 'anthropic' } },
    ])
    await expect(disconnect).toBeDisabled()
    await response(page, 'model_subscription_disconnect', {
      success: false, provider: 'anthropic', message: 'Could not verify logout.',
      status: { supported: true, configured: true, connected: false, error: 'Could not verify logout.' },
    })
    await expect(disconnect).toBeEnabled()
    await expect(page.getByRole('alert')).toContainText('Could not verify logout.')
    await disconnect.click()
    expect(await sent(page, 'model_subscription_disconnect')).toHaveLength(2)
    await response(page, 'model_subscription_disconnect', {
      success: true, provider: 'anthropic',
      status: { supported: true, connected: false },
    })
    await expect(disconnect).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Sign in with Claude', exact: true })).toBeEnabled()
    await expect(page.getByRole('alert')).toHaveCount(0)
    if (screen === 'settings') {
      await page.getByRole('button', { name: 'Test Connection', exact: true }).click()
      expect(await sent(page, 'model_connection_test')).toHaveLength(1)
    }
  })

  test(`${screen}: invalid login can sign in again`, async ({ page }) => {
    await page.goto(`/tests/subscription-recovery.html?screen=${screen}`)
    const signIn = page.getByRole('button', { name: 'Sign in with Claude', exact: true })
    await signIn.click()
    expect(await sent(page, 'model_subscription_connect')).toEqual([
      { type: 'model_subscription_connect', data: { provider: 'anthropic' } },
    ])
    await response(page, 'model_subscription_connect', {
      success: true, provider: 'anthropic', active_provider: 'anthropic',
      status: { supported: true, configured: true, connected: true, email: 'test@example.com' },
    })
    await expect(signIn).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Disconnect', exact: true })).toBeEnabled()
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
}
