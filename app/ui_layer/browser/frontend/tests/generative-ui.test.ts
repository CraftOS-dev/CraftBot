import { test, expect, type Page } from '@playwright/test'

const preview = (page: Page) => page.frameLocator('iframe')
// A 1x1 PNG, for map tiles and stored images.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')
async function previewAction(page: Page, name: string) {
  const button = page.getByRole('button', { name, exact: true })
  if (!await button.isVisible()) await page.getByLabel('Preview options', { exact: true }).click()
  await button.click()
  if (name === 'Reset saved progress') await page.getByRole('button', { name: 'Reset progress', exact: true }).click()
}
async function open(page: Page) {
  await page.route('**/api/agent-profile-picture', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#FF4F18"/></svg>' }))
  await page.route('**/api/generative-ui/tiles', route => route.fulfill({ json: { attribution: 'Test tiles', maxZoom: 18 } }))
  await page.route('**/api/generative-ui/tiles/*/*/*', route => route.fulfill({ contentType: 'image/png', body: PNG }))
  await page.goto('/tests/generative-ui.html')
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
}
// The round button at the chat's top left: opens the outputs, or closes them when on show.
const outputsButton = (page: Page) => page.getByRole('button', { name: 'Show outputs', exact: true })
const seam = (page: Page) => page.getByRole('separator', { name: 'Resize conversation and output' })
async function custom(page: Page, html: string, connect_origins: string[] = [], extra: Record<string, unknown> = {}) {
  await page.evaluate(({ html, connect_origins, extra }) => window.dispatchEvent(new CustomEvent('fixture-artifact', { detail: { id: 'custom', title: 'Custom interface', revision: 1, html, connect_origins, ...extra } })), { html, connect_origins, extra })
}
// The page records what its content policy blocked (the panel shows no page errors).
const REPORT_BLOCKED = `<script>addEventListener('securitypolicyviolation', e => { const root = document.documentElement; root.dataset.blocked = ((root.dataset.blocked || '') + ' ' + e.violatedDirective).trim() })</script>`
const blocked = (page: Page) => preview(page).locator('html')

const cookingStateKey = 'craftbot.ui.chat.artifactState.["demo","cooking"]'
const controlsHTML = `<label>Count<input id="count" type="number" value="2"></label><output id="total"></output>
<script>document.getElementById('total').textContent = Number(document.getElementById('count').value) * 3;</script>`

test('progress follows new tabs, edits and resets without restarting local interactions', async ({ page, context }) => {
  await open(page)
  const original = await page.locator('iframe').getAttribute('srcdoc')
  await preview(page).getByLabel('Servings').fill('5')
  await preview(page).getByLabel('Servings').press('Tab')
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  expect(await page.locator('iframe').getAttribute('srcdoc')).toBe(original)
  await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}').step, cookingStateKey)).toBe(1)
  const other = await context.newPage() // No opener: sessionStorage cannot be copied.
  await open(other)
  await expect(preview(other).getByLabel('Servings')).toHaveValue('5')
  await expect(preview(other).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  await preview(other).getByRole('button', { name: 'Next step' }).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 3 of 4' })).toBeVisible()
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('2')
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('5')
  await previewAction(other, 'Reset saved progress')
  await expect(preview(page).getByLabel('Servings')).toHaveValue('2')
  await expect(preview(page).getByRole('heading', { name: 'Step 1 of 4' })).toBeVisible()
  await other.close()
})

test('native controls and derived output hydrate when another tab saves', async ({ page, context }) => {
  await open(page)
  await custom(page, controlsHTML, [], { persistence: 'controls' })
  const other = await context.newPage()
  await open(other)
  await custom(other, controlsHTML, [], { persistence: 'controls' })
  await preview(page).getByLabel('Count').fill('9')
  await expect(preview(other).getByLabel('Count')).toHaveValue('9')
  await expect(preview(other).locator('#total')).toHaveText('27')
  await preview(other).getByLabel('Count').fill('11')
  await expect(preview(page).getByLabel('Count')).toHaveValue('11')
  await expect(preview(page).locator('#total')).toHaveText('33')
  await other.getByRole('button', { name: 'Cooking', exact: true }).click()
  await expect(preview(other).getByLabel('Servings')).toHaveValue('2')
  await other.close()
})

test('manual and native progress survive closing Chromium and reopening its disk profile', async ({ browser }, testInfo) => {
  const profile = testInfo.outputPath('persistent-profile')
  let context = await browser.browserType().launchPersistentContext(profile, { headless: true })
  try {
    let page = await context.newPage()
    await open(page)
    await preview(page).getByLabel('Servings').fill('6')
    await preview(page).getByLabel('Servings').press('Tab')
    await preview(page).getByRole('checkbox').first().check()
    await preview(page).getByRole('button', { name: 'Next step' }).click()
    await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}').step, cookingStateKey)).toBe(1)
    await custom(page, controlsHTML, [], { persistence: 'controls' })
    await preview(page).getByLabel('Count').fill('13')
    await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('craftbot.ui.chat.artifactState.["demo","custom"]') || '{}').count)).toBe('13')
    await context.close()
    context = await browser.browserType().launchPersistentContext(profile, { headless: true })
    page = await context.newPage()
    await open(page)
    await expect(preview(page).getByLabel('Servings')).toHaveValue('6')
    await expect(preview(page).getByRole('checkbox').first()).toBeChecked()
    await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
    await custom(page, controlsHTML, [], { persistence: 'controls' })
    await expect(preview(page).getByLabel('Count')).toHaveValue('13')
    await expect(preview(page).locator('#total')).toHaveText('39')
  } finally {
    await context.close()
  }
})

test('legacy tab progress migrates once and never overwrites durable progress', async ({ page }) => {
  await page.addInitScript(key => {
    sessionStorage.setItem(key, JSON.stringify({ servings: 4, step: 1 }))
  }, cookingStateKey)
  await open(page)
  await expect(preview(page).getByLabel('Servings')).toHaveValue('4')
  expect(await page.evaluate(key => sessionStorage.getItem(key), cookingStateKey)).toBeNull()
  await preview(page).getByLabel('Servings').fill('7')
  await preview(page).getByLabel('Servings').press('Tab')
  await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}').servings, cookingStateKey)).toBe(7)
  await page.reload() // Deliberately reintroduces an old tab's stale value.
  await expect(preview(page).getByLabel('Servings')).toHaveValue('7')
})

test('valid legacy progress replaces malformed durable data', async ({ page }) => {
  await page.addInitScript(key => {
    sessionStorage.setItem(key, JSON.stringify({ servings: 4 }))
    localStorage.setItem(key, '[1,2]')
  }, cookingStateKey)
  await open(page)
  await expect(preview(page).getByLabel('Servings')).toHaveValue('4')
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}').servings, cookingStateKey)).toBe(4)
})

test('an older buffered write cannot undo a reset from another tab', async ({ page, context }) => {
  await page.clock.install()
  await open(page)
  await page.clock.pauseAt(new Date())
  await preview(page).getByLabel('Servings').fill('4')
  await preview(page).getByLabel('Servings').press('Tab')
  await expect(preview(page).getByText('400 g pasta')).toBeVisible()
  const other = await context.newPage()
  await open(other)
  await previewAction(other, 'Reset saved progress')
  await other.evaluate(() => window.dispatchEvent(new Event('pagehide')))
  await expect(preview(page).getByLabel('Servings')).toHaveValue('2')
  await page.clock.runFor(500)
  expect(await page.evaluate(key => localStorage.getItem(key), cookingStateKey)).toBe('{}')
  await other.close()
})

for (const action of ['reset', 'close']) test(`durable ${action} cannot resurrect progress from a stale legacy tab`, async ({ page }) => {
  await page.addInitScript(key => sessionStorage.setItem(key, JSON.stringify({ servings: 8 })), cookingStateKey)
  await open(page)
  await expect(preview(page).getByLabel('Servings')).toHaveValue('8')
  if (action === 'reset') await previewAction(page, 'Reset saved progress')
  else await page.getByRole('button', { name: 'Close Cooking guide', exact: true }).click()
  await expect.poll(() => page.evaluate(key => localStorage.getItem(key), cookingStateKey)).toBe('{}')
  await page.reload()
  if (action === 'close') await outputsButton(page).click()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('2')
})

test('a new tab sees the latest progress without waiting for a flush timer', async ({ page, context }) => {
  await page.clock.install()
  await open(page)
  await page.clock.pauseAt(new Date())
  await preview(page).getByLabel('Servings').fill('8')
  await preview(page).getByLabel('Servings').press('Tab')
  await expect(preview(page).getByText('800 g pasta')).toBeVisible()
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}').servings, cookingStateKey)).toBe(8)
  const other = await context.newPage()
  await open(other)
  await expect(preview(other).getByLabel('Servings')).toHaveValue('8')
  await other.close()
})

test('delayed storage notifications cannot roll back newer local progress', async ({ page }) => {
  await open(page)
  await preview(page).getByLabel('Servings').fill('9')
  await preview(page).getByLabel('Servings').press('Tab')
  await expect(preview(page).getByText('900 g pasta')).toBeVisible()
  await page.evaluate(key => window.dispatchEvent(new StorageEvent('storage', {
    key, storageArea: localStorage, oldValue: '{}', newValue: '{"servings":4}',
  })), cookingStateKey)
  await expect(preview(page).getByLabel('Servings')).toHaveValue('9')
  await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}').servings, cookingStateKey)).toBe(9)
})

for (const event of ['chat_clear', 'session_cleared', 'session_deleted']) test(`${event} resets saved outputs outside loaded history and isolates other chats`, async ({ page, context }) => {
  await open(page)
  await preview(page).getByLabel('Servings').fill('7')
  await preview(page).getByLabel('Servings').press('Tab')
  await expect(preview(page).getByText('700 g pasta')).toBeVisible()
  const other = await context.newPage()
  await open(other)
  await expect(preview(other).getByLabel('Servings')).toHaveValue('7')
  await page.evaluate(async event => {
    const { store } = await import('./harness.tsx')
    const { setUiState } = await import('../src/store/slices/uiSlice')
    const { UI_STATE } = await import('../src/store/uiState')
    const { dispatchInbound } = await import('../src/store/socket/messageRegistry.ts')
    store.dispatch(setUiState(UI_STATE.chat.artifactState('["demo","older-output"]'), { count: 17 }))
    store.dispatch(setUiState(UI_STATE.chat.artifactState('["other","cooking"]'), { servings: 6 }))
    dispatchInbound({ type: event, data: { sessionId: 'demo' } }, store.dispatch, store.getState as never)
  }, event)
  await expect(preview(other).getByLabel('Servings')).toHaveValue('2')
  await other.close()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('2')
  await expect.poll(() => page.evaluate(() => [
    localStorage.getItem('craftbot.ui.chat.artifactState.["demo","cooking"]'),
    localStorage.getItem('craftbot.ui.chat.artifactState.["demo","older-output"]'),
    JSON.parse(localStorage.getItem('craftbot.ui.chat.artifactState.["other","cooking"]') || '{}').servings,
  ])).toEqual(['{}', '{}', 6])
  await page.reload()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('2')
})

test('a full durable storage area preserves legacy progress for a later retry', async ({ page }) => {
  await page.addInitScript(key => {
    sessionStorage.setItem(key, JSON.stringify({ servings: 4 }))
    const write = Storage.prototype.setItem
    Storage.prototype.setItem = function (key, value) {
      if (this === localStorage) throw new DOMException('Full', 'QuotaExceededError')
      write.call(this, key, value)
    }
  }, cookingStateKey)
  await open(page)
  await expect(preview(page).getByLabel('Servings')).toHaveValue('4')
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key) || '{}').servings, cookingStateKey)).toBe(4)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
})

test('cooking controls persist across unmount, reload and revision; reset clears progress', async ({ page }) => {
  await open(page)
  await preview(page).getByLabel('Servings').fill('4')
  await preview(page).getByLabel('Servings').press('Tab')
  await preview(page).getByRole('checkbox').first().check()
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  await preview(page).getByRole('button', { name: 'Start 10-minute timer' }).click()
  await expect(preview(page).getByText('400 g pasta')).toBeVisible()
  await page.getByRole('button', { name: 'Leave preview' }).click()
  await page.getByRole('button', { name: 'Return to preview' }).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  await expect(preview(page).getByRole('checkbox').first()).toBeChecked()
  await expect(preview(page).locator('#timer')).toContainText('remaining')
  await page.getByRole('button', { name: 'Revise interface' }).click()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('4')
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).some(key => key.includes('artifactState')))).toBe(true)
  await page.reload()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('4')
  await previewAction(page, 'Reset saved progress')
  await expect(preview(page).getByLabel('Servings')).toHaveValue('2')
  await expect(preview(page).getByRole('checkbox').first()).not.toBeChecked()
  await expect(preview(page).locator('#timer')).toContainText('No timer')
})

test('state is scoped to each chat session; pause and retry restore it', async ({ page }) => {
  await open(page)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 1 of 4' })).toBeVisible()
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  await previewAction(page, 'Pause preview')
  await expect(page.locator('iframe')).toHaveCount(0)
  await previewAction(page, 'Resume preview')
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  await previewAction(page, 'Reload preview')
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
})

test('outputs stay live outside virtualized messages and reopen with progress', async ({ page }) => {
  await open(page)
  await expect(page.getByRole('region', { name: 'Output panel' })).toBeVisible()
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  const document = await page.locator('iframe').getAttribute('srcdoc')
  await page.getByRole('button', { name: 'Hide message' }).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  expect(await page.locator('iframe').getAttribute('srcdoc')).toBe(document)
  await outputsButton(page).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.reload()
  await expect(page.locator('iframe')).toHaveCount(0)
  await outputsButton(page).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
})

test('new revisions open after closing, with selectable history and one running document', async ({ page }) => {
  await open(page)
  await custom(page, '<p>New output</p>')
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-history', { detail: [
    { id: 'custom', title: 'Custom interface', revision: 0, html: '<p>Previous output</p>', connect_origins: [] },
  ] })))
  // One tab per output; its revisions are in the options menu.
  await expect(page.getByRole('tab')).toHaveCount(1)
  await page.getByLabel('Preview options', { exact: true }).click()
  await page.getByRole('button', { name: 'Version 0', exact: true }).click()
  await expect(preview(page).getByText('Previous output')).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(1)
  await outputsButton(page).click()
  await page.getByRole('button', { name: 'Revise interface' }).click()
  await expect(preview(page).getByText('New output')).toBeVisible()
  await page.getByLabel('Preview options', { exact: true }).click()
  await expect(page.getByRole('button', { name: 'Version 2', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'Version 0', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByRole('tab')).toHaveCount(1)
  await expect(page.locator('iframe')).toHaveCount(1)
})

test('output visibility belongs to its session and older history does not reopen it', async ({ page }) => {
  await open(page)
  await outputsButton(page).click()
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-history', { detail: [
    { id: 'older', title: 'Older output', revision: 1, html: '<p>Older history</p>', connect_origins: [] },
  ] })))
  await expect(page.locator('iframe')).toHaveCount(0)
  await outputsButton(page).click()
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
})

test('the output is the pane on desktop and switches itself to phone width in a narrow pane, without reloading', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  const document = await page.locator('iframe').getAttribute('srcdoc')
  const pane = page.getByRole('region', { name: 'Output panel' })
  // No manual viewport switch: the output's name is its tab, in a Chrome-like strip.
  await expect(page.getByRole('button', { name: 'Phone', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Desktop', exact: true })).toHaveCount(0)
  await expect(pane.getByRole('tab', { name: 'Cooking guide', exact: true })).toHaveAttribute('aria-selected', 'true')
  // Desktop: the output fills the pane edge to edge below the strip, no frame around it.
  const paneBox = (await pane.boundingBox())!
  const frameBox = (await page.locator('iframe').boundingBox())!
  expect(frameBox.x).toBeCloseTo(paneBox.x, 0)
  expect(frameBox.width).toBeCloseTo(paneBox.width, 0)
  expect(frameBox.y).toBeCloseTo(paneBox.y + 36, 0)
  expect(frameBox.y + frameBox.height).toBeCloseTo(paneBox.y + paneBox.height, 0)
  // Too narrow for side by side: the panel above, the chat (with its buttons)
  // below, and a pane under 440px shows the output at phone width.
  await page.setViewportSize({ width: 420, height: 844 })
  await expect(seam(page)).toHaveAttribute('aria-orientation', 'horizontal')
  await expect.poll(async () => (await page.locator('iframe').boundingBox())!.width).toBeCloseTo(390, 0)
  const panel = (await pane.boundingBox())!
  expect(panel.y + panel.height).toBeLessThanOrEqual((await outputsButton(page).boundingBox())!.y)
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  // Wide again: back to desktop, the same running document.
  await page.setViewportSize({ width: 1440, height: 900 })
  await expect.poll(async () => (await page.locator('iframe').boundingBox())!.width).toBeCloseTo((await pane.boundingBox())!.width, 0)
  expect(await page.locator('iframe').getAttribute('srcdoc')).toBe(document)
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  await outputsButton(page).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  await expect(outputsButton(page)).toBeVisible()
})

test('ready previews stay ready when the app synchronizes its language', async ({ page }) => {
  await page.clock.install()
  await open(page)
  await expect(page.getByRole('status')).toHaveCount(0)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-language', { detail: 'es' })))
  await expect(page.locator('html')).toHaveAttribute('lang', 'es')
  await page.clock.fastForward(11_000)
  await expect(page.getByRole('status')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
})

test('reopening during an animated close keeps the running document and progress', async ({ page }) => {
  await open(page)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  const document = await page.locator('iframe').getAttribute('srcdoc')
  // Pause the native exit at its start to exercise cancellation deterministically.
  await outputsButton(page).evaluate(element => {
    element.addEventListener('click', () => requestAnimationFrame(() => {
      document.getAnimations().forEach(animation => animation.pause())
    }), { once: true })
  })
  await outputsButton(page).click()
  await outputsButton(page).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  expect(await page.locator('iframe').getAttribute('srcdoc')).toBe(document)
  await outputsButton(page).click()
  await expect(page.locator('iframe')).toHaveCount(0)
})

test('reduced motion disables panel and preview transitions without changing controls', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await open(page)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  const panel = page.getByRole('region', { name: 'Output panel' })
  await expect.poll(() => panel.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0)
  await expect(preview(page).getByRole('button', { name: 'Next step' })).toHaveCSS('transition-duration', '0s')
  await outputsButton(page).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  await outputsButton(page).click()
  expect(await seam(page).locator('..').evaluate(element => element.getAnimations().length)).toBe(0)
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  await outputsButton(page).click()
  await expect(page.locator('iframe')).toHaveCount(0)
})

test('chat and panel move through intermediate layouts when closing and opening', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  const document = await page.locator('iframe').getAttribute('srcdoc')
  const workspace = page.getByRole('region', { name: 'Output panel', includeHidden: true }).locator('..')
  const chat = workspace.locator(':scope > div').last()
  const splitWidth = (await chat.boundingBox())!.width

  const pauseAtStart = async () => {
    await outputsButton(page).evaluate(element => {
      element.addEventListener('click', () => requestAnimationFrame(() => {
        for (const animation of document.getAnimations()) {
          if (animation.effect instanceof KeyframeEffect && animation.effect.getKeyframes().some(frame => 'gridTemplateColumns' in frame)) {
            animation.pause()
            animation.currentTime = 0
          }
        }
      }), { once: true })
    })
    await outputsButton(page).click()
  }
  const seek = async (time: number | 'finish') => {
    await page.evaluate(time => {
      for (const animation of document.getAnimations()) {
        if (animation.effect instanceof KeyframeEffect && animation.effect.getKeyframes().some(frame => 'gridTemplateColumns' in frame)) {
          if (time === 'finish') animation.finish()
          else animation.currentTime = time
        }
      }
    }, time)
  }

  await pauseAtStart()
  expect((await chat.boundingBox())!.width).toBeCloseTo(splitWidth, 0)
  await seek(150)
  const closingWidth = (await chat.boundingBox())!.width
  expect(closingWidth).toBeGreaterThan(splitWidth + 1)
  expect(closingWidth).toBeLessThan(1439)
  await seek('finish')
  await expect(page.locator('iframe')).toHaveCount(0)

  await pauseAtStart()
  expect((await chat.boundingBox())!.width).toBeCloseTo(1440, 0)
  await seek(150)
  const openingWidth = (await chat.boundingBox())!.width
  expect(openingWidth).toBeGreaterThan(splitWidth + 1)
  expect(openingWidth).toBeLessThan(1439)
  await seek('finish')
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  expect((await chat.boundingBox())!.width).toBeCloseTo(splitWidth, 0)
  expect(await page.locator('iframe').getAttribute('srcdoc')).not.toBe(document) // Closing unloads.
})

test('resize supports dragging and keyboard, persists, and preserves the running document', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  const document = await page.locator('iframe').getAttribute('srcdoc')
  const handle = seam(page)
  await expect(handle).toHaveAttribute('aria-orientation', 'vertical')
  const initial = Number(await handle.getAttribute('aria-valuenow'))
  await handle.press('ArrowRight')
  await expect.poll(async () => Number(await handle.getAttribute('aria-valuenow'))).toBeGreaterThan(initial)
  const rect = (await handle.boundingBox())!
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2)
  await page.mouse.down()
  await page.mouse.move(rect.x - 140, rect.y + rect.height / 2, { steps: 8 })
  await page.mouse.up()
  const resized = await handle.getAttribute('aria-valuenow')
  expect(Number(resized)).toBeLessThan(initial)
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  expect(await page.locator('iframe').getAttribute('srcdoc')).toBe(document)
  await page.reload()
  await expect(handle).toHaveAttribute('aria-valuenow', resized!)
  await handle.press('Home')
  await expect.poll(async () => await handle.getAttribute('aria-valuenow')).toBe(await handle.getAttribute('aria-valuemin'))
  await handle.press('End')
  await expect.poll(async () => await handle.getAttribute('aria-valuenow')).toBe(await handle.getAttribute('aria-valuemax'))
  // A wide browser can still contain a narrow workspace next to the app
  // sidebar: the panel stacks above the chat, which stays on screen.
  await handle.locator('..').evaluate(element => (element as HTMLElement).style.width = '800px')
  await expect(handle).toHaveAttribute('aria-orientation', 'horizontal')
  await expect(page.getByRole('region', { name: 'Output panel' })).toBeVisible()
  await expect(outputsButton(page)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test("the panel sits on the chat's left; its buttons are round icons at the chat's top left", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await page.getByRole('button', { name: 'Add browser' }).click()
  const panel = (await page.getByRole('region', { name: 'Output panel' }).boundingBox())!
  const outputs = (await outputsButton(page).boundingBox())!
  const browser = page.getByRole('button', { name: "Show this chat's browser", exact: true })
  // Panel, seam, then the chat with its buttons in the top left corner.
  const workspace = (await seam(page).locator('..').boundingBox())!
  expect(panel.x).toBe(workspace.x)
  expect(outputs.x).toBeGreaterThan(panel.x + panel.width)
  expect(outputs.x - (panel.x + panel.width)).toBeLessThan(24)
  expect(outputs.y - workspace.y).toBeLessThan(24)
  expect((await browser.boundingBox())!.x).toBeGreaterThan(outputs.x)
  // Icons only, round; no conversation bar, and the output's own bar shows its name.
  for (const button of [outputsButton(page), browser]) {
    expect((await button.innerText()).trim()).toBe('')
    await expect(button).toHaveCSS('border-radius', '50%')
  }
  await expect(page.getByText('Conversation', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Fullscreen output' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Back to conversation' })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Output panel' }).getByRole('tab', { name: 'Cooking guide', exact: true })).toBeVisible()
  // The one on show is pressed.
  await expect(outputsButton(page)).toHaveAttribute('aria-expanded', 'true')
  await expect(browser).toHaveAttribute('aria-expanded', 'false')
  await browser.click()
  await expect(outputsButton(page)).toHaveAttribute('aria-expanded', 'false')
  await expect(browser).toHaveAttribute('aria-expanded', 'true')
  expect((await page.getByRole('region', { name: 'Browser panel' }).boundingBox())!.x).toBe(workspace.x)
})

test("the seam closes the panel on a click, on Enter, or when dragged to the panel's edge", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  const handle = seam(page)
  // A click (no drag) closes the panel; focus goes to the panel's button.
  await handle.click()
  await expect(page.locator('iframe')).toHaveCount(0)
  await expect(outputsButton(page)).toBeFocused()
  // Dragged into the panel's collapse zone, it animates shut (as on a click)
  // and keeps its size.
  await outputsButton(page).click()
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
  // The seam is where it settles once the panel has finished opening.
  await expect.poll(() => handle.locator('..').evaluate(element => element.getAnimations().length)).toBe(0)
  const size = await handle.getAttribute('aria-valuenow')
  const rect = (await handle.boundingBox())!
  const workspace = (await handle.locator('..').boundingBox())!
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2)
  await page.mouse.down()
  // Held at its smallest size, just outside the collapse zone ...
  await page.mouse.move(workspace.x + 420, rect.y + rect.height / 2, { steps: 6 })
  // ... the pane's width on every frame from here on (-1 once it is gone).
  await page.evaluate(() => {
    const widths: number[] = []
    ;(window as unknown as { paneWidths: number[] }).paneWidths = widths
    const sample = () => {
      const pane = document.querySelector('[aria-label="Output panel"]')
      widths.push(pane ? pane.getBoundingClientRect().width : -1)
      if (widths.length < 60) requestAnimationFrame(sample)
    }
    requestAnimationFrame(sample)
  })
  const before = (await page.getByRole('region', { name: 'Output panel' }).boundingBox())!.width
  await page.mouse.move(workspace.x + 120, rect.y + rect.height / 2, { steps: 8 })
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.mouse.up()
  const widths = await page.evaluate(() => (window as unknown as { paneWidths: number[] }).paneWidths)
  expect(widths.filter(width => width > 1 && width < before - 1).length).toBeGreaterThanOrEqual(3)
  await outputsButton(page).click()
  await expect(handle).toHaveAttribute('aria-valuenow', size!)
  // Enter closes it from the keyboard.
  await handle.focus()
  await handle.press('Enter')
  await expect(page.locator('iframe')).toHaveCount(0)
  await expect(outputsButton(page)).toBeFocused()
})

test('stacked, the panel sits above the chat and the seam resizes and closes it vertically', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await page.getByRole('button', { name: 'Stack panel' }).click()
  const handle = seam(page)
  await expect(handle).toHaveAttribute('aria-orientation', 'horizontal')
  const panel = (await page.getByRole('region', { name: 'Output panel' }).boundingBox())!
  const seamBox = (await handle.boundingBox())!
  expect(panel.y + panel.height).toBeLessThanOrEqual(seamBox.y + 1)
  expect((await outputsButton(page).boundingBox())!.y).toBeGreaterThan(seamBox.y)
  const initial = Number(await handle.getAttribute('aria-valuenow'))
  await handle.press('ArrowDown')
  await expect.poll(async () => Number(await handle.getAttribute('aria-valuenow'))).toBeGreaterThan(initial)
  const rect = (await handle.boundingBox())!
  await page.mouse.move(rect.x + rect.width / 2, rect.y)
  await page.mouse.down()
  await page.mouse.move(rect.x + rect.width / 2, rect.y - 120, { steps: 8 })
  await page.mouse.up()
  expect(Number(await handle.getAttribute('aria-valuenow'))).toBeLessThan(initial)
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
  // Dragged to the top, it closes.
  const moved = (await handle.boundingBox())!
  const workspace = (await handle.locator('..').boundingBox())!
  await page.mouse.move(moved.x + moved.width / 2, moved.y)
  await page.mouse.down()
  await page.mouse.move(moved.x + moved.width / 2, workspace.y + 20, { steps: 12 })
  await page.mouse.up()
  await expect(page.locator('iframe')).toHaveCount(0)
})

const notesOutput = { id: 'notes', title: 'Notes', revision: 1, html: '<h1>Notes page</h1>', connect_origins: [] }

test("outputs are tabs like the browser's, with reload and options at the strip's right end", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await page.evaluate(output => window.dispatchEvent(new CustomEvent('fixture-history', { detail: [output] })), notesOutput)
  const pane = page.getByRole('region', { name: 'Output panel' })
  const tabs = pane.getByRole('tab')
  await expect(tabs).toHaveCount(2)
  await expect(tabs.nth(0)).toHaveText('Notes')
  await expect(pane.getByRole('tab', { name: 'Cooking guide', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('combobox')).toHaveCount(0) // no picker any more
  await pane.getByRole('tab', { name: 'Notes', exact: true }).click()
  await expect(preview(page).getByRole('heading', { name: 'Notes page' })).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(1)
  // Reload and options sit in the strip, right of the last tab.
  const strip = await pane.getByRole('tablist').evaluate(element => element.parentElement!.getBoundingClientRect().toJSON())
  const lastTab = (await tabs.last().boundingBox())!
  const reload = (await pane.getByRole('button', { name: 'Reload preview', exact: true }).boundingBox())!
  const options = (await pane.getByLabel('Preview options', { exact: true }).boundingBox())!
  expect(reload.x).toBeGreaterThan(lastTab.x + lastTab.width)
  expect(options.x).toBeGreaterThan(reload.x)
  for (const box of [reload, options]) {
    expect(box.y).toBeGreaterThanOrEqual(strip.top)
    expect(box.y + box.height).toBeLessThanOrEqual(strip.bottom)
  }
})

test('closing an output tab disposes of it: its progress and tab go, the last one closes the panel', async ({ page }) => {
  await open(page)
  await page.evaluate(output => window.dispatchEvent(new CustomEvent('fixture-history', { detail: [output] })), notesOutput)
  const savedCooking = () => page.evaluate(() => Object.keys(JSON.parse(localStorage.getItem('craftbot.ui.chat.artifactState.["demo","cooking"]') || '{}')).length > 0 ? 1 : 0)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  await expect.poll(savedCooking).toBe(1)
  const pane = page.getByRole('region', { name: 'Output panel' })
  await pane.getByRole('button', { name: 'Close Cooking guide', exact: true }).click()
  // Its saved progress goes with it; the tab next to it takes its place.
  await expect(pane.getByRole('tab')).toHaveCount(1)
  await expect(pane.getByRole('tab', { name: 'Notes', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(preview(page).getByRole('heading', { name: 'Notes page' })).toBeVisible()
  await expect.poll(savedCooking).toBe(0)
  // The conversation keeps it listed, closed: nothing to open.
  await expect(page.getByText('Closed', { exact: true })).toBeVisible()
  // Closing the last output closes the panel; no outputs, no outputs button.
  await pane.getByRole('button', { name: 'Close Notes', exact: true }).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  await expect(outputsButton(page)).toHaveCount(0)
})

test('reset requires confirmation, can be cancelled, and preview options dismiss outside', async ({ page }) => {
  await open(page)
  await preview(page).getByLabel('Servings').fill('4')
  await preview(page).getByLabel('Servings').press('Tab')
  await page.getByLabel('Preview options', { exact: true }).click()
  await page.getByRole('button', { name: 'Reset saved progress', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('4')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('4')
  await page.getByRole('heading', { name: 'An answer you can use.', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Reset saved progress' })).toBeHidden()
  await page.getByLabel('Preview options', { exact: true }).click()
  await preview(page).getByLabel('Servings').click()
  await expect(page.getByRole('button', { name: 'Reset saved progress' })).toBeHidden()
  await previewAction(page, 'Reset saved progress')
  await expect(preview(page).getByLabel('Servings')).toHaveValue('2')
})

test('quick history hydration creates a ready frame with the latest token', async ({ page }) => {
  await page.clock.install()
  await open(page)
  const html = '<p id="hydrated">Hydrated interface</p><script>window.craftbot.saveState({loaded: true});</script>'
  await custom(page, html)
  // History hydration can replace an artifact with an equal object while its
  // previous srcdoc is still loading. Each document must have a fresh Window.
  for (let i = 0; i < 5; i++) await custom(page, html)
  await expect(preview(page).locator('#hydrated')).toHaveText('Hydrated interface')
  await expect(page.getByRole('status')).toHaveCount(0)
  await page.clock.fastForward(11_000)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('preview follows host theme without reloading or losing interactions', async ({ page }) => {
  await open(page)
  await custom(page, '<h1>Theme-aware answer</h1><button id="count">Count 0</button><script>let count = 0; document.getElementById("count").addEventListener("click", e => { e.target.textContent = "Count " + (++count); window.craftbot.saveState({count}); });</script>')
  await preview(page).getByRole('button', { name: 'Count 0' }).click()
  const initialDocument = await page.locator('iframe').getAttribute('srcdoc')
  await expect(preview(page).locator('html')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await page.evaluate(() => document.documentElement.dataset.theme = 'dark')
  await expect(preview(page).locator('html')).toHaveCSS('background-color', 'rgb(25, 25, 25)')
  await expect(preview(page).getByRole('button', { name: 'Count 1' })).toBeVisible()
  expect(await page.locator('iframe').getAttribute('srcdoc')).toBe(initialDocument)
  await expect(page.getByLabel('Preview options', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Reset saved progress' })).toBeHidden()
  await page.getByLabel('Preview options', { exact: true }).press('Enter')
  await expect(page.getByRole('button', { name: 'Reset saved progress' })).toBeVisible()
  await page.getByLabel('Preview options', { exact: true }).press('Escape')
  await expect(page.getByRole('button', { name: 'Reset saved progress' })).toBeHidden()
})

test('weather calls approved APIs, switches units locally, refreshes, and reports failures', async ({ page }) => {
  let forecasts = 0
  await page.route('https://geocoding-api.open-meteo.com/**', route => route.fulfill({ json: { results: [{ name: 'London', latitude: 51.5, longitude: -0.1 }] }, headers: { 'access-control-allow-origin': '*' } }))
  await page.route('https://api.open-meteo.com/**', route => {
    forecasts++
    return forecasts > 2 ? route.fulfill({ status: 503, body: 'Unavailable', headers: { 'access-control-allow-origin': '*' } }) : route.fulfill({ json: { current: { temperature_2m: 20, time: '2026-10-08T10:00' }, hourly: { time: ['2026-10-08T10:00', '2026-10-08T11:00'], temperature_2m: [20, 21] } }, headers: { 'access-control-allow-origin': '*' } })
  })
  await open(page)
  await page.getByRole('button', { name: 'Weather', exact: true }).click()
  await preview(page).getByRole('button', { name: 'Find weather' }).click()
  await expect(preview(page).locator('#temperature')).toHaveText('20.0°C')
  await expect(preview(page).locator('#hours .hour')).toHaveCount(2)
  await expect(preview(page).locator('#updated')).toContainText('Last fetched:')
  await preview(page).getByLabel('Temperature', { exact: true }).selectOption('fahrenheit')
  await expect(preview(page).locator('#temperature')).toHaveText('68.0°F')
  expect(forecasts).toBe(1)
  await preview(page).getByRole('button', { name: 'Refresh forecast' }).click()
  await expect.poll(() => forecasts).toBe(2)
  await expect(preview(page).getByRole('button', { name: 'Refresh forecast' })).toBeEnabled()
  await preview(page).getByRole('button', { name: 'Refresh forecast' }).click()
  await expect(preview(page).getByRole('status').first()).toContainText('Unable to load weather')
})

test('API origins are declared per output, with undeclared destinations and redirects blocked', async ({ page }) => {
  const requests: string[] = []
  await page.route('https://data.example.org/**', route => {
    requests.push(route.request().url())
    return route.fulfill({ json: { count: 42 }, headers: { 'access-control-allow-origin': '*' } })
  })
  await page.route('https://api.example.com/**', route => route.fulfill({
    status: 302, headers: { location: 'https://other.example.com/redirected', 'access-control-allow-origin': '*' },
  }))
  const denied: string[] = []
  await page.route('https://other.example.com/**', route => { denied.push(route.request().url()); return route.abort() })
  await open(page)
  await custom(page, `${REPORT_BLOCKED}<p id="data">Loading</p><script>
    fetch('https://data.example.org/count').then(r => r.json()).then(d => document.getElementById('data').textContent = 'Count ' + d.count);
    fetch('https://other.example.com/undeclared').catch(() => {});
    fetch('https://api.example.com/redirect').catch(() => {});
  </script>`, ['https://DATA.example.org:443/', 'https://api.example.com'])
  await expect(preview(page).locator('#data')).toHaveText('Count 42')
  await expect(blocked(page)).toHaveAttribute('data-blocked', /connect-src/)
  expect(requests).toEqual(['https://data.example.org/count'])
  expect(denied).toEqual([])
})

for (const origins of [
  ['https://data.example.org; connect-src *'],
  ['https://data.example.org\n'],
  ['https://data.example.org', 'https://127.0.0.1'],
  ['https://app.localhost'],
  ['https://data.example.org/path'],
]) test(`invalid persisted API policy fails closed: ${JSON.stringify(origins)}`, async ({ page }) => {
  const requests: string[] = []
  await page.route('https://data.example.org/**', route => { requests.push(route.request().url()); return route.abort() })
  await open(page)
  await custom(page, `${REPORT_BLOCKED}<p>Invalid policy</p><script>fetch('https://data.example.org/count').catch(() => {});</script>`, origins)
  await expect(blocked(page)).toHaveAttribute('data-blocked', /connect-src/)
  expect(requests).toEqual([])
})

test('design controls, menu and form work on a narrow viewport and with keyboard input', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await open(page)
  await page.getByRole('button', { name: 'Design', exact: true }).click()
  await preview(page).getByLabel('Card spacing').focus()
  await preview(page).getByLabel('Card spacing').press('ArrowRight')
  await expect(preview(page).locator('#card')).toHaveCSS('padding', '25px')
  await preview(page).getByLabel('Accent color').fill('#123456')
  await expect(preview(page).getByRole('button', { name: 'Join the preview' })).toHaveCSS('background-color', 'rgb(18, 52, 86)')
  await preview(page).getByRole('button', { name: 'Menu', exact: true }).click()
  await expect(preview(page).getByRole('navigation')).toBeVisible()
  await preview(page).getByLabel('Email address').fill('test@example.com')
  await preview(page).getByRole('button', { name: 'Join the preview' }).click()
  await expect(preview(page).getByRole('status')).toContainText('submitted locally')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('sandbox denies parent/storage access, external scripts and undeclared fetch, even with a copied nonce', async ({ page }) => {
  await open(page)
  const outgoing: string[] = []
  await page.route('https://blocked.invalid/**', route => { outgoing.push(route.request().url()); return route.abort() })
  await custom(page, `${REPORT_BLOCKED}<meta http-equiv="refresh" content="0;url=https://blocked.invalid/refresh"><img src="https://blocked.invalid/image"><iframe src="https://blocked.invalid/frame"></iframe><p id="result"></p><script>
    const results = [];
    try { parent.document.body; results.push('parent-access'); } catch { results.push('parent-blocked'); }
    try { localStorage.getItem('secret'); results.push('storage-access'); } catch { results.push('storage-blocked'); }
    document.getElementById('result').textContent = results.join(',');
    const script = document.createElement('script'); script.nonce = document.querySelector('script').nonce; script.src = 'https://blocked.invalid/script.js'; document.body.append(script);
    fetch('https://blocked.invalid/data').catch(() => {});
  </script>`)
  await expect(preview(page).locator('#result')).toHaveText('parent-blocked,storage-blocked')
  await expect(blocked(page)).toHaveAttribute('data-blocked', /script-src/)
  await expect(blocked(page)).toHaveAttribute('data-blocked', /connect-src/)
  expect(outgoing).toEqual([])
  await expect(page.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts allow-forms')
})

test('page errors stay out of the panel, forged messages are ignored and oversized state is rejected', async ({ page }) => {
  await open(page)
  await page.evaluate(() => window.postMessage({ channel: 'craftbot-generative-ui', type: 'state', state: { forged: true }, token: document.querySelector('iframe')?.srcdoc.match(/const token = "([^"]+)/)?.[1] }, '*'))
  await custom(page, `<p id="result"></p><script>try { window.craftbot.saveState({ text: 'x'.repeat(70000) }) } catch (error) { document.getElementById('result').textContent = error.message }</script>`)
  await expect(preview(page).locator('#result')).toHaveText('State exceeds 64 KB')
  await custom(page, `<p>Broken example</p><script>throw new Error('Example runtime failure')</script><script>Promise.reject(new Error('Rejected'))</script><img src="https://blocked.invalid/image">`)
  await expect(preview(page).getByText('Broken example')).toBeVisible()
  await previewAction(page, 'Reload preview')
  await expect(preview(page).getByText('Broken example')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('forged')
})

test('document attributes and state strings survive rendering without executing injected markup', async ({ page }) => {
  await open(page)
  await custom(page, '<html lang="fr"><body class="test-body" style="background:rgb(1, 2, 3);color:rgb(23, 21, 18)"><p id="value"></p><button id="save">Save text</button><script>document.getElementById("value").textContent = window.craftbot.state.text || "Initial"; document.getElementById("save").addEventListener("click", () => window.craftbot.saveState({text: "<" + "/script><script>throw new Error(123)<" + "/script>"}));</script></body></html>')
  await expect(preview(page).locator('html')).toHaveAttribute('lang', 'fr')
  await expect(preview(page).locator('body')).toHaveClass('test-body')
  await expect(preview(page).locator('body')).toHaveCSS('background-color', 'rgb(1, 2, 3)')
  await expect(preview(page).getByRole('button', { name: 'Save text' })).toHaveCSS('color', 'rgb(23, 21, 18)')
  await preview(page).getByRole('button', { name: 'Save text' }).click()
  await previewAction(page, 'Reload preview')
  await expect(preview(page).locator('#value')).toHaveText('</script><script>throw new Error(123)</script>')
  await expect(page.getByRole('alert')).toHaveCount(0)
})

for (const panel of ['browser', 'closed'] as const) {
  test(`the first incoming output opens when the panel is ${panel}`, async ({ page }) => {
    await page.goto('/tests/generative-ui.html?empty')
    await page.getByRole('button', { name: 'Add browser' }).click()
    const browserButton = page.getByRole('button', { name: "Show this chat's browser", exact: true })
    await browserButton.click()
    await expect(page.getByRole('region', { name: 'Browser panel' })).toBeVisible()
    if (panel === 'closed') {
      await browserButton.click()
      await expect(page.getByRole('region', { name: 'Browser panel' })).toHaveCount(0)
    }
    await expect(outputsButton(page)).toHaveCount(0)
    await custom(page, '<p>First incoming output</p>')
    await expect(page.getByRole('region', { name: 'Output panel' })).toBeVisible()
    await expect(preview(page).getByText('First incoming output')).toBeVisible()
    await expect(page.getByRole('region', { name: 'Browser panel' })).toHaveCount(0)
  })
}

test('the browser shares the panel with outputs, one at a time', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Add browser' }).click()
  // The panel's browser button opens the browser in place of the output.
  await page.getByRole('button', { name: "Show this chat's browser", exact: true }).click()
  await expect(page.getByRole('region', { name: 'Browser panel' })).toBeVisible()
  await expect(page.getByText('Fake browser')).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(0)
  // Outputs take it back; the output kept its place.
  await outputsButton(page).click()
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Browser panel' })).toHaveCount(0)
  // A new output switches the panel from the browser to it.
  await page.getByRole('button', { name: "Show this chat's browser", exact: true }).click()
  await page.getByRole('button', { name: 'Revise interface' }).click()
  await expect(page.getByRole('region', { name: 'Output panel' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Browser panel' })).toHaveCount(0)
  // The browser button toggles: a second press closes the panel.
  await page.getByRole('button', { name: "Show this chat's browser", exact: true }).click()
  await page.getByRole('button', { name: "Show this chat's browser", exact: true }).click()
  await expect(page.getByRole('region', { name: 'Browser panel' })).toHaveCount(0)
  await expect(page.locator('iframe')).toHaveCount(0)
})

test('the browser opens by itself when the agent starts browsing, per session', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Add browser' }).click()
  await outputsButton(page).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.getByRole('button', { name: 'Agent starts browsing' }).click()
  await expect(page.getByRole('region', { name: 'Browser panel' })).toBeVisible()
  // The opening animates like any other.
  await expect.poll(() => page.evaluate(() => document.getAnimations().length)).toBeGreaterThan(0)
  // Each chat has its own panel: the other session's panel is untouched.
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(page.getByRole('region', { name: 'Browser panel' })).toHaveCount(0)
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(page.getByRole('region', { name: 'Browser panel' })).toBeVisible()
})

// Bundling a library the first time can take the dev server several seconds.
const LIBRARY_LOAD = { timeout: 60_000 }

test('libraries load as globals before the page code runs, without any network request', async ({ page }) => {
  await open(page)
  const outgoing: string[] = []
  page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:7935/') && !request.url().startsWith('data:')) outgoing.push(request.url()) })
  await custom(page, `<div id="map" style="height:200px"></div><canvas id="chart"></canvas><i data-lucide="map-pin"></i><p id="result"></p><script>
    const results = [typeof L.map, typeof THREE.Scene, typeof THREE.OrbitControls, typeof Chart, typeof Motion.animate, typeof Motion.stagger, typeof lucide.createIcons];
    lucide.createIcons();
    const map = L.map('map').setView([51.5, -0.1], 13);
    L.marker([51.5, -0.1]).addTo(map);
    new Chart(document.getElementById('chart'), { type: 'bar', data: { labels: ['a', 'b'], datasets: [{ data: [1, 2] }] } });
    Motion.animate('#result', { opacity: [0, 1] }, { duration: 0.2 });
    document.getElementById('result').textContent = results.join(',');
  </script>`, [], { libraries: ['chart', 'leaflet', 'lucide', 'motion', 'three'] })
  await expect(preview(page).locator('#result')).toHaveText('function,function,function,function,function,function,function', LIBRARY_LOAD)
  await expect(preview(page).locator('svg.lucide-map-pin')).toBeVisible()
  // Leaflet's marker and stylesheet images are inline.
  await expect.poll(() => preview(page).locator('.leaflet-marker-icon').evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  await expect(preview(page).locator('.leaflet-pane').first()).toHaveCSS('position', 'absolute')
  await expect.poll(() => preview(page).locator('#chart').evaluate(canvas => (canvas as HTMLCanvasElement).width)).toBeGreaterThan(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(outgoing).toEqual([])
})

test('only listed libraries load, and an invalid persisted list loads none', async ({ page }) => {
  await open(page)
  const probe = `<p id="result"></p><script>document.getElementById('result').textContent = [typeof L, typeof THREE, typeof Chart].join(',')</script>`
  await custom(page, probe, [], { libraries: ['chart'] })
  await expect(preview(page).locator('#result')).toHaveText('undefined,undefined,function', LIBRARY_LOAD)
  await custom(page, probe, [], { libraries: ['chart', 'jquery'] })
  await expect(preview(page).locator('#result')).toHaveText('undefined,undefined,undefined')
})

test('libraries follow a reduced-motion preference', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await open(page)
  await custom(page, `<p id="result"></p><script>document.getElementById('result').textContent = [Motion.MotionGlobalConfig.skipAnimations, Chart.defaults.animation].join(',')</script>`, [], { libraries: ['chart', 'motion'] })
  await expect(preview(page).locator('#result')).toHaveText('true,false', LIBRARY_LOAD)
})

test('maps get their tiles through CraftBot; web images load from declared origins only', async ({ page }) => {
  await open(page)
  const tiles: string[] = []
  page.on('request', request => { if (request.url().includes('/api/generative-ui/tiles/')) tiles.push(new URL(request.url()).pathname) })
  const photos: string[] = []
  await page.route('https://photos.example.com/**', route => { photos.push(route.request().url()); return route.fulfill({ contentType: 'image/png', body: PNG }) })
  const denied: string[] = []
  await page.route('https://tile.example.org/**', route => { denied.push(route.request().url()); return route.abort() })
  await custom(page, `${REPORT_BLOCKED}<div id="map" style="height:200px"></div><div id="other" style="height:100px"></div><img id="photo" src="https://photos.example.com/cat.png"><script>
    L.map('map').setView([51.5, -0.1], 3).addLayer(L.tileLayer.craftbot());
    L.tileLayer('https://tile.example.org/{z}/{x}/{y}.png').addTo(L.map('other').setView([0, 0], 1));
  </script>`, [], { libraries: ['leaflet'], image_origins: ['https://Photos.Example.com'] })
  await expect.poll(() => preview(page).locator('#map .leaflet-tile-loaded').count(), LIBRARY_LOAD).toBeGreaterThan(0)
  expect(tiles.length).toBeGreaterThan(0)
  expect(tiles.every(path => /^\/api\/generative-ui\/tiles\/3\/\d+\/\d+$/.test(path))).toBe(true)
  await expect(preview(page).locator('#map .leaflet-control-attribution')).toContainText('Test tiles')
  await expect.poll(() => preview(page).locator('#photo').evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(1)
  expect(photos).toHaveLength(1)
  // A tile server the page names itself is never contacted.
  await expect(blocked(page)).toHaveAttribute('data-blocked', /img-src/)
  expect(denied).toEqual([])
})

test('colours follow the host theme: tokens, light-dark(), charts, map controls and a theme event', async ({ page }) => {
  await open(page)
  await custom(page, `<div id="box" style="color: light-dark(rgb(1, 1, 1), rgb(2, 2, 2))">Box</div><p id="events">0</p><div id="map" style="height:120px"></div><canvas id="chart"></canvas><script>
    let events = 0;
    addEventListener('craftbot-theme', () => { document.getElementById('events').textContent = String(++events) });
    L.map('map').setView([51.5, -0.1], 3).addLayer(L.tileLayer.craftbot());
    window.chart = new Chart(document.getElementById('chart'), { type: 'bar', data: { labels: ['a'], datasets: [{ data: [1] }] } });
  </script>`, [], { libraries: ['chart', 'leaflet'] })
  const box = preview(page).locator('#box')
  await expect(box).toHaveCSS('color', 'rgb(1, 1, 1)', LIBRARY_LOAD)
  const tickColor = () => preview(page).locator('#chart').evaluate(() => (window as unknown as { chart: { scales: { x: { options: { ticks: { color: string } } } } } }).chart.scales.x.options.ticks.color)
  const lightTicks = await tickColor()
  const zoom = preview(page).locator('.leaflet-control-zoom-in')
  const lightZoom = await zoom.evaluate(element => getComputedStyle(element).backgroundColor)
  await page.evaluate(() => document.documentElement.dataset.theme = 'dark')
  await expect(box).toHaveCSS('color', 'rgb(2, 2, 2)')
  await expect(preview(page).locator('#events')).toHaveText('1')
  await expect.poll(tickColor).not.toBe(lightTicks)
  await expect.poll(() => zoom.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe(lightZoom)
  // The load handshake re-sends the same theme: no event for an unchanged theme.
  await previewAction(page, 'Reload preview')
  await expect(preview(page).locator('#box')).toHaveCSS('color', 'rgb(2, 2, 2)')
  await expect(preview(page).locator('#events')).toHaveText('0')
})

test('stored images reach the page as window.craftbot.images; an unavailable one can be retried', async ({ page }) => {
  let available = true
  const fetched: string[] = []
  await page.route('**/api/generative-ui/**', route => {
    fetched.push(new URL(route.request().url()).pathname)
    return available ? route.fulfill({ contentType: 'image/png', body: PNG }) : route.fulfill({ status: 404, body: '' })
  })
  await open(page)
  const path = '0123456789abcdef/custom/fedcba9876543210.png'
  const html = `<img id="hero" alt="Hero"><p id="names"></p><script>
    document.getElementById('hero').src = window.craftbot.images.hero;
    document.getElementById('names').textContent = Object.keys(window.craftbot.images).join(',') || 'none';
  </script>`
  await custom(page, html, [], { images: { hero: path } })
  await expect(preview(page).locator('#names')).toHaveText('hero')
  await expect.poll(() => preview(page).locator('#hero').evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(1)
  expect(fetched).toEqual([`/api/generative-ui/${path}`])
  // Invalid persisted metadata loads no images and fetches nothing.
  await custom(page, html, [], { images: { hero: '../chat.db' } })
  await expect(preview(page).locator('#names')).toHaveText('none')
  expect(fetched).toHaveLength(1)
  available = false
  await custom(page, html, [], { images: { hero: path.replace('custom', 'other') } })
  await expect(page.getByRole('alert')).toContainText('Image "hero" is unavailable (404)')
  available = true
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(preview(page).locator('#names')).toHaveText('hero')
})


test('declared native controls persist without author save handlers and hydrate before derived scripts', async ({ page }) => {
  await open(page)
  const html = `<form>
    <label>Budget<input type="number" id="budget" value="10"></label>
    <label>Done<input type="checkbox" id="done"></label>
    <label for="notes">Notes</label><textarea id="notes">initial</textarea>
    <label for="city">City</label><select id="city"><option value="ldn">London</option><option value="par">Paris</option></select>
    <label>A<input type="radio" name="kind" value="a" data-craftbot-state="kind" checked></label>
    <label>B<input type="radio" name="kind" value="b" data-craftbot-state="kind"></label>
    <label for="tags">Tags</label><select id="tags" multiple><option value="x">X</option><option value="y">Y</option></select>
    <input type="password" id="secret"><input type="file" id="file">
    <button type="reset">Reset fields</button><output id="derived"></output>
    </form><script>document.getElementById('derived').textContent = document.getElementById('budget').value * 3;</script>`
  await custom(page, html, [], { persistence: 'controls' })
  await preview(page).getByLabel('Budget', { exact: true }).fill('37')
  await preview(page).getByLabel('Done', { exact: true }).check()
  await preview(page).getByLabel('Notes', { exact: true }).fill('Saved notes')
  await preview(page).getByLabel('City', { exact: true }).selectOption('par')
  await preview(page).getByLabel('B', { exact: true }).check()
  await preview(page).getByLabel('Tags', { exact: true }).selectOption(['x', 'y'])
  await preview(page).locator('#secret').fill('never persist me')
  await previewAction(page, 'Reload preview')
  await expect(preview(page).getByLabel('Budget', { exact: true })).toHaveValue('37')
  await expect(preview(page).getByLabel('Done', { exact: true })).toBeChecked()
  await expect(preview(page).getByLabel('Notes', { exact: true })).toHaveValue('Saved notes')
  await expect(preview(page).getByLabel('City', { exact: true })).toHaveValue('par')
  await expect(preview(page).getByLabel('B', { exact: true })).toBeChecked()
  await expect(preview(page).getByLabel('Tags', { exact: true })).toHaveValues(['x', 'y'])
  await expect(preview(page).locator('#secret')).toHaveValue('')
  await expect(preview(page).locator('#derived')).toHaveText('111')
  // A revision changes markup but keeps the declared stable keys.
  await custom(page, html.replace('value="10"', 'value="20"'), [], { persistence: 'controls', revision: 2 })
  await expect(preview(page).getByLabel('Budget', { exact: true })).toHaveValue('37')
  await expect(preview(page).locator('#derived')).toHaveText('111')
  await previewAction(page, 'Reset saved progress')
  await expect(preview(page).getByLabel('Budget', { exact: true })).toHaveValue('20')
  await expect(preview(page).getByLabel('Done', { exact: true })).not.toBeChecked()
})


test('implicit option values and empty radio values restore with native HTML semantics', async ({ page }) => {
  await open(page)
  await custom(page, `<label for="destination">Destination</label>
    <select id="destination"><option>Home</option><option>  New \n York  </option></select>
    <label>Unset<input type="radio" name="choice" data-craftbot-state="choice" value="" checked></label>
    <label>Set<input type="radio" name="choice" data-craftbot-state="choice" value="set"></label>`, [], { persistence: 'controls' })
  await preview(page).getByLabel('Destination').selectOption({ label: 'New York' })
  await preview(page).getByLabel('Set', { exact: true }).check()
  await preview(page).getByLabel('Unset', { exact: true }).check()
  await previewAction(page, 'Reload preview')
  await expect(preview(page).getByLabel('Destination')).toHaveValue('New York')
  await expect(preview(page).getByLabel('Unset', { exact: true })).toBeChecked()
})
