import { test, expect, type Page } from '@playwright/test'

const preview = (page: Page) => page.frameLocator('iframe')
async function previewAction(page: Page, name: string) {
  const button = page.getByRole('button', { name, exact: true })
  if (!await button.isVisible()) await page.getByLabel('Preview options', { exact: true }).click()
  await button.click()
}
async function open(page: Page) {
  await page.route('**/api/agent-profile-picture', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#FF4F18"/></svg>' }))
  await page.goto('/tests/generative-ui.html')
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
}
async function custom(page: Page, html: string, connect_origins: string[] = []) {
  await page.evaluate(({ html, connect_origins }) => window.dispatchEvent(new CustomEvent('fixture-artifact', { detail: { id: 'custom', title: 'Custom interface', revision: 1, html, connect_origins } })), { html, connect_origins })
}

test('cooking controls persist across unmount, expansion, reload and revision; reset clears progress', async ({ page }) => {
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
  await page.getByRole('button', { name: 'Fullscreen output', exact: true }).click()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('4')
  await page.getByRole('button', { name: 'Exit fullscreen', exact: true }).click()
  await page.getByRole('button', { name: 'Revise interface' }).click()
  await expect(preview(page).getByLabel('Servings')).toHaveValue('4')
  await expect.poll(() => page.evaluate(() => Object.keys(sessionStorage).some(key => key.includes('artifactState')))).toBe(true)
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
  await page.getByRole('button', { name: 'Back to conversation' }).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.reload()
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.getByRole('button', { name: 'Show outputs', exact: true }).click()
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
})

test('new revisions open after closing, with selectable history and one running document', async ({ page }) => {
  await open(page)
  await custom(page, '<p>New output</p>')
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-history', { detail: [
    { id: 'custom', title: 'Custom interface', revision: 0, html: '<p>Previous output</p>', connect_origins: [] },
  ] })))
  await page.getByLabel('Select output revision').selectOption('custom:0')
  await expect(preview(page).getByText('Previous output')).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(1)
  await page.getByRole('button', { name: 'Back to conversation' }).click()
  await page.getByRole('button', { name: 'Revise interface' }).click()
  await expect(preview(page).getByText('New output')).toBeVisible()
  await expect(page.getByLabel('Select output revision')).toHaveValue('custom:2')
  await expect(page.locator('iframe')).toHaveCount(1)
})

test('output visibility belongs to its session and older history does not reopen it', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Back to conversation' }).click()
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
  await page.getByRole('button', { name: 'Switch session' }).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('fixture-history', { detail: [
    { id: 'older', title: 'Older output', revision: 1, html: '<p>Older history</p>', connect_origins: [] },
  ] })))
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.getByRole('button', { name: 'Show outputs', exact: true }).click()
  await expect(preview(page).getByRole('heading', { name: 'Weeknight tomato pasta' })).toBeVisible()
})

test('phone viewport and fullscreen change canvas space without reloading the document', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await preview(page).getByRole('button', { name: 'Next step' }).click()
  const document = await page.locator('iframe').getAttribute('srcdoc')
  await page.getByRole('button', { name: 'Phone', exact: true }).click()
  expect((await page.locator('iframe').boundingBox())!.width).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: 'Fullscreen output', exact: true }).click()
  await page.getByRole('button', { name: 'Desktop', exact: true }).click()
  expect((await page.locator('iframe').boundingBox())!.width).toBeGreaterThan(1000)
  expect(await page.locator('iframe').getAttribute('srcdoc')).toBe(document)
  await expect(preview(page).getByRole('heading', { name: 'Step 2 of 4' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Exit fullscreen', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Output panel' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Back to conversation' }).click()
  await expect(page.getByRole('button', { name: 'Show outputs', exact: true })).toBeVisible()
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
  await custom(page, `<p id="data">Loading</p><script>
    fetch('https://data.example.org/count').then(r => r.json()).then(d => document.getElementById('data').textContent = 'Count ' + d.count);
    fetch('https://other.example.com/undeclared').catch(() => {});
    fetch('https://api.example.com/redirect').catch(() => {});
  </script>`, ['https://DATA.example.org:443/', 'https://api.example.com'])
  await expect(preview(page).locator('#data')).toHaveText('Count 42')
  await expect(page.getByRole('alert')).toContainText('Blocked resource:')
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
  await custom(page, `<p>Invalid policy</p><script>fetch('https://data.example.org/count').catch(() => {});</script>`, origins)
  await expect(page.getByRole('alert')).toContainText('Blocked resource:')
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
  await custom(page, `<meta http-equiv="refresh" content="0;url=https://blocked.invalid/refresh"><img src="https://blocked.invalid/image"><iframe src="https://blocked.invalid/frame"></iframe><p id="result"></p><script>
    const results = [];
    try { parent.document.body; results.push('parent-access'); } catch { results.push('parent-blocked'); }
    try { localStorage.getItem('secret'); results.push('storage-access'); } catch { results.push('storage-blocked'); }
    document.getElementById('result').textContent = results.join(',');
    const script = document.createElement('script'); script.nonce = document.querySelector('script').nonce; script.src = 'https://blocked.invalid/script.js'; document.body.append(script);
    fetch('https://blocked.invalid/data').catch(() => {});
  </script>`)
  await expect(preview(page).locator('#result')).toHaveText('parent-blocked,storage-blocked')
  await expect(page.getByRole('alert')).toContainText('Blocked resource:')
  expect(outgoing).toEqual([])
  await expect(page.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts allow-forms')
})

test('runtime errors are visible, forged messages are ignored and oversized state is rejected', async ({ page }) => {
  await open(page)
  await page.evaluate(() => window.postMessage({ channel: 'craftbot-generative-ui', type: 'error', message: 'forged', token: document.querySelector('iframe')?.srcdoc.match(/const token = "([^"]+)/)?.[1] }, '*'))
  await expect(page.getByRole('alert')).toHaveCount(0)
  await custom(page, `<script>window.craftbot.saveState({ text: 'x'.repeat(70000) });</script>`)
  await expect(page.getByRole('alert')).toContainText('State exceeds 64 KB')
  await custom(page, `<p>Broken example</p><script>throw new Error('Example runtime failure')</script>`)
  await expect(page.getByRole('alert')).toContainText('Example runtime failure')
  await previewAction(page, 'Reload preview')
  await expect(page.getByRole('alert')).toContainText('Example runtime failure')
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
