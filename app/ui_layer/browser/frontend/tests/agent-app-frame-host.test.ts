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
    const idleEvicted = !host.hasIframe('two') && host.hasIframe('one')
    const source = second.frame.dataset.requestedSrc
    const sameFrame = host.getOrCreateIframe('one', url) === second.frame && second.frame.dataset.requestedSrc === source
    const wrongOriginRejected = !host.acceptsFrameMessage('one', new MessageEvent('message', { source: second.frame.contentWindow, origin: 'https://example.com' }))
    const correctOriginAccepted = host.acceptsFrameMessage('one', new MessageEvent('message', { source: second.frame.contentWindow, origin: 'http://localhost:7935' }))
    replacement.release(); second.release(); leases.forEach(lease => lease.release())
    host.reconcileIframes([])
    return { conflict, staleProtected, capacity, idleEvicted, sameFrame, wrongOriginRejected, correctOriginAccepted, disposed: !host.hasIframe('one') }
  })
  expect(Object.values(result).every(Boolean)).toBe(true)
})

test('persisted panel references validate and removing the selected app chooses a neighbor', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html')
  const result = await page.evaluate(async () => {
    const state = await import('/src/features/agentApps/panelAppsState.ts')
    const first = state.attachPanelApp(state.emptyPanelApps, 'one')
    const second = state.attachPanelApp(first, 'two')
    return {
      duplicate: state.attachPanelApp(second, 'one').projectIds,
      remaining: state.retainPanelApps(second, id => id !== 'two'),
      invalid: [{}, null, { projectIds: ['a', 'a'], selectedProjectId: 'a' }, { projectIds: ['a'], selectedProjectId: 'b' }, { projectIds: [5], selectedProjectId: null }].map(state.isPanelAppsState),
    }
  })
  expect(result.duplicate).toEqual(['one', 'two'])
  expect(result.remaining).toEqual({ projectIds: ['one'], selectedProjectId: 'one' })
  expect(result.invalid).toEqual([false, false, false, false, false])
})
