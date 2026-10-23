import { expect, test } from '@playwright/test'

// These flags provide synthetic devices and synthetic screen frames. The
// tests never access the user's microphone, camera or desktop.
test.use({
  launchOptions: {
    args: [
      '--use-fake-device-for-media-stream',
      '--use-fake-ui-for-media-stream',
      '--auto-select-desktop-capture-source=Entire screen',
    ],
  },
  permissions: ['camera', 'microphone'],
})

test('Agent App frames delegate microphone and camera across origins', async ({ page }) => {
  await page.goto('/tests/agent-app-media.html')
  const frame = page.frameLocator('iframe[title="Cross-origin Agent App media fixture"]')
  await frame.getByRole('button', { name: 'Test microphone and camera', exact: true }).click()
  await expect(frame.locator('#result')).toHaveText('audio,video')
  await expect(page.locator('iframe')).toHaveAttribute('allow', /microphone; camera; display-capture/)
})

test('Agent App frames delegate screen capture across origins', async ({ page }) => {
  await page.goto('/tests/agent-app-media.html')
  const frame = page.frameLocator('iframe[title="Cross-origin Agent App media fixture"]')
  await frame.getByRole('button', { name: 'Test screen capture', exact: true }).click()
  await expect(frame.locator('#result')).toHaveText('video')
})
