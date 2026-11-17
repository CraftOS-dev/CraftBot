import { expect, test } from '@playwright/test'

test('leases protect owners, survive stale releases, and evict only idle frames', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  const result = await page.evaluate(async () => {
    const host = await import('/src/features/agentApps/frameHost.ts')
    const url = 'http://localhost:7935/tests/fixtures/panel-app.html'
    const first = host.acquireIframe('one', url)!
    const conflict = host.acquireIframe('one', url) === null
    first.release()
    const second = host.acquireIframe('one', url)!
    first.release()
    const staleProtected = host.acquireIframe('one', url) === null
    const leases = ['two', 'three', 'four', 'five'].map(id => host.acquireIframe(id, url)!)
    const capacity = host.acquireIframe('six', url) === null
    leases[0].release()
    const replacement = host.acquireIframe('six', url)!
    const idleEvicted = !leases[0].frame.isConnected && second.frame.isConnected
    const source = second.frame.dataset.requestedSrc
    const sameFrame = host.getOrCreateIframe('one', url) === second.frame && second.frame.dataset.requestedSrc === source
    replacement.release(); second.release(); leases.forEach(lease => lease.release())
    host.reconcileFrameworkIframes([])
    return { conflict, staleProtected, capacity, idleEvicted, sameFrame, disposed: !second.frame.isConnected }
  })
  expect(Object.values(result).every(Boolean)).toBe(true)
})

test('a frame that loads while no surface holds it is reported as loaded', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  const result = await page.evaluate(async () => {
    const host = await import('/src/features/agentApps/frameHost.ts')
    const lease = host.acquireIframe('background', 'http://localhost:7935/tests/fixtures/panel-app.html?background')!
    const loaded = new Promise(resolve => lease.frame.addEventListener('load', resolve, { once: true }))
    const beforeLoad = host.isIframeLoaded('background')
    lease.release()
    await loaded
    const afterLoad = host.isIframeLoaded('background')
    host.removeIframe('background')
    return { beforeLoad, afterLoad }
  })
  expect(result).toEqual({ beforeLoad: false, afterLoad: true })
})

test('themes reach active and parked apps, survive reload, and clear custom overrides', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await page.evaluate(async () => {
    const host = await import('/src/features/agentApps/frameHost.ts')
    const apps = ['one', 'two'].map(id => ({ id, path: `C:/theme/${id}`, uiTheme: { themeId: id === 'one' ? 'ocean' : 'forest' } }))
    host.syncFrameworkThemes('light', apps)
    for (const app of apps) {
      const lease = host.acquireIframe(host.frameworkFrameId(app.path, app.id), `http://localhost:7935/tests/fixtures/panel-app.html?${app.id}`)!
      lease.frame.title = app.id
      if (app.id === 'two') lease.release()
    }
  })
  const one = page.frameLocator('iframe[title="one"]').locator('#theme')
  const two = page.frameLocator('iframe[title="two"]').locator('#theme')
  await expect(one).toHaveText('ocean:light')
  await expect(two).toHaveText('forest:light')
  const colors = { bg: '#123456', surface: '#234567', text: '#ffffff', accent: '#ff0000' }
  await page.evaluate(async colors => {
    const host = await import('/src/features/agentApps/frameHost.ts')
    host.syncFrameworkThemes('dark', [
      { id: 'one', path: 'C:/theme/one', uiTheme: { themeId: 'custom', customColors: colors } },
      { id: 'two', path: 'C:/theme/two', uiTheme: { themeId: 'forest' } },
    ])
  }, colors)
  await expect(one).toHaveAttribute('data-message', JSON.stringify({ type: 'livingui-theme', themeId: 'craftbot', mode: 'dark', customColors: colors }))
  await expect(two).toHaveText('forest:dark')
  const child = page.frames().find(frame => frame.url().endsWith('?one'))!
  await child.goto(child.url())
  await expect(one).toHaveText('craftbot:dark')
  await page.evaluate(async () => {
    const host = await import('/src/features/agentApps/frameHost.ts')
    host.syncFrameworkThemes('dark', [{ id: 'one', path: 'C:/theme/one', uiTheme: { themeId: 'ocean' } }])
  })
  await expect(one).toHaveAttribute('data-message', JSON.stringify({ type: 'livingui-theme', themeId: 'ocean', mode: 'dark' }))
})

test('theme replay accepts only the registered frame and its exact origin', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  await page.evaluate(async () => {
    const host = await import('/src/features/agentApps/frameHost.ts')
    host.syncFrameworkThemes('dark', [{ path: 'C:/theme/one', id: 'one', uiTheme: { themeId: 'forest' } }])
    host.acquireIframe(host.frameworkFrameId('C:/theme/one', 'one'), 'http://localhost:7935/tests/fixtures/panel-app.html?replay')
  })
  const output = page.frameLocator('iframe').locator('#theme')
  await expect(output).toHaveText('forest:dark')
  const child = page.frames().find(frame => frame.url().endsWith('?replay'))!
  await child.waitForLoadState('load')
  // Drain the initial load + readiness replies before probing rejected senders.
  await child.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await child.evaluate(() => { document.querySelector('#theme')!.textContent = 'unchanged' })
  await page.evaluate(() => {
    const source = document.querySelector('iframe')!.contentWindow
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'craftbot-theme-request' }, source, origin: 'http://wrong.example' }))
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'craftbot-theme-request' }, source: window, origin: 'http://localhost:7935' }))
  })
  await expect(output).toHaveText('unchanged')
  await child.evaluate(() => parent.postMessage({ type: 'craftbot-theme-request' }, '*'))
  await expect(output).toHaveText('forest:dark')
})
