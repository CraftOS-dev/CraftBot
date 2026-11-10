import { openFrameworkSettings } from './helpers/framework-settings'
import { expect, test, type Page } from '@playwright/test'

const requests = (page: Page, operation: string) => page.evaluate(operation => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_request' && r.operation === operation), operation)
const reply = (page: Page, requestId: string, result: unknown) => page.evaluate(({ requestId, result }) => (window as any).panelReceive({ type: 'agent_app_framework_response', data: { requestId, status: 'success', result } }), { requestId, result })
const socketMessage = (page: Page, type: string, data: unknown) => page.evaluate(message => (window as any).panelReceiveSocket(message), { type, data })
const wizardRequests = (page: Page, type = 'agent_app_wizard_finalize') => page.evaluate(type => (window as any).panelRequests.filter((r: any) => r.type === type), type)
async function setup(page: Page) {
  await page.setViewportSize({ width: 1280, height: 850 })
  await page.goto('/tests/panel-agent-apps.html?permissions-menu')
  await expect(page.getByRole('button', { name: 'Add Agent App', exact: true })).toBeVisible()
}

test('native install stays in the existing toast and opens the installed app without a management page', async ({ page }, info) => {
  await setup(page)
  await page.getByRole('button', { name: 'Add Agent App', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Add Agent App', exact: true })).toBeVisible()
  await expect.poll(async () => (await requests(page, 'catalogue')).length).toBeGreaterThan(0)
  const catalog = (await requests(page, 'catalogue')).at(-1)
  await reply(page, catalog.requestId, { status: 'success', data: { apps: [{
    id: 'notes-board', name: 'Notes board', description: 'Notes',
    folder: 'legacy-notes', customizable: [{ key: 'APP_TITLE', label: 'Old title field', type: 'text', default: 'Notes' }],
  }] } })
  await page.getByRole('dialog').getByRole('button', { name: 'Add', exact: true }).click()
  await expect.poll(async () => (await requests(page, 'inspect')).length).toBe(1)
  await reply(page, (await requests(page, 'inspect'))[0].requestId, { status: 'success', data: { installable: true } })
  await expect.poll(async () => (await requests(page, 'install')).length).toBe(1)
  const req = (await requests(page, 'install'))[0]
  expect(req.package).toEqual({ id: 'notes-board' })
  const job = { id: req.requestId, request: req.package, status: 'running', steps: [{ step: 'dependencies', status: 'start' }] }
  await page.evaluate(job => { (window as any).frameworkState.jobs = [job] }, job)
  await reply(page, req.requestId, job)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('Installing app…', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'View activity', exact: true })).toHaveCount(0)
  await expect(page.getByText('dependencies: start', { exact: true })).toHaveCount(0)
  await page.evaluate(job => {
    (window as any).frameworkState.jobs = [{ ...job, status: 'success', result: { dir: '/installed/notes', id: 'installed-notes', served: true } }];
    (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [{ id: 'installed-notes', name: 'Notes board', path: '/installed/notes', status: 'running' }], connected: [] } } })
  }, job)
  await expect(page.getByRole('button', { name: 'Open app', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Open app', exact: true }).click()
  await expect.poll(() => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_open').at(-1)?.appId)).toBe('installed-notes')
  expect(await requests(page, 'workflow')).toEqual([])
  expect(await page.evaluate(() => (window as any).panelRequests.some((r: any) => ['agent_app_create', 'agent_app_marketplace_install', 'agent_app_import'].includes(r.type)))).toBe(false)
  await page.screenshot({ path: info.outputPath('framework-install.png') })
})

test('old management links redirect to the existing Agent App settings', async ({ page }) => {
  await page.goto('/tests/panel-agent-apps.html?permissions-menu&route=/apps')
  await expect(page.getByRole('main').getByRole('button', { name: 'Agent App', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: 'Notes settings', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Install activity', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Convert with agent', exact: true })).toHaveCount(0)
})

test('new app requests use the upstream workflow and disconnected mutations are disabled', async ({ page }) => {
  await setup(page)
  await page.getByRole('button', { name: 'Add Agent App', exact: true }).click()
  await page.getByRole('button', { name: 'Create Custom', exact: true }).click()
  await page.getByPlaceholder('e.g., World News Dashboard', { exact: true }).fill('Shared notes')
  await page.getByRole('dialog').getByRole('textbox').last().fill('A shared notes app')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect.poll(async () => (await requests(page, 'workflow')).length).toBe(1)
  const request = (await requests(page, 'workflow'))[0]
  expect(request.activity).toBe('create')
  expect(request.request).toContain('A shared notes app')
  expect(request.request).toContain('Shared notes')
  expect(request.creation).toEqual({ name: 'Shared notes', authMode: 'none' })
  expect(await page.evaluate(() => (window as any).panelRequests.some((r: any) => r.type === 'agent_app_wizard_interview'))).toBe(false)
  await page.evaluate(requestId => (window as any).panelReceive({ type: 'agent_app_framework_response', data: { requestId, status: 'error', message: 'Fixture unavailable' } }), request.requestId)
  await expect(page.getByRole('alert')).toContainText('Fixture unavailable')
  await page.evaluate(() => (window as any).panelStore.dispatch({ type: 'connection/setConnected', payload: false }))
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
})

test('the chat wizard retains its originating session through retry, follow-up questions and completion', async ({ page }) => {
  await setup(page)
  const wizard = {
    wizardId: 'chat-wizard', originSessionId: 'notes-chat', config: { name: 'Chat notes', description: 'Organise notes' },
    questions: [{ id: 'audience', question: 'Who will use this app?', multiSelect: false, options: ['Just me', 'My team'] }],
  }
  await socketMessage(page, 'agent_app_wizard_open', wizard)
  const dialog = page.getByRole('dialog', { name: 'Chat notes — setup questions', exact: true })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('radio', { name: 'My team', exact: true }).check()
  await dialog.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect.poll(async () => (await wizardRequests(page)).length).toBe(1)
  const first = (await wizardRequests(page))[0]
  expect(first).toMatchObject({
    wizardId: wizard.wizardId, originSessionId: wizard.originSessionId, followupDone: false,
    config: { name: 'Chat notes' }, answers: [{ id: 'audience', question: 'Who will use this app?', answer: 'My team' }],
  })
  await socketMessage(page, 'agent_app_wizard_finalize', { wizardId: 'unrelated-wizard', success: true, projectId: 'other' })
  await socketMessage(page, 'agent_app_wizard_finalize', { wizardId: wizard.wizardId, success: false, error: 'Please retry setup' })
  await expect(dialog).toContainText('Please retry setup')
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(async () => (await wizardRequests(page)).length).toBe(2)
  expect((await wizardRequests(page))[1]).toEqual(first)
  await socketMessage(page, 'agent_app_wizard_finalize', {
    wizardId: wizard.wizardId, success: true,
    followupQuestions: [{ id: 'layout', question: 'Which layout?', multiSelect: false, options: ['Board', 'List'] }],
  })
  await dialog.getByRole('radio', { name: 'Board', exact: true }).check()
  await dialog.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect.poll(async () => (await wizardRequests(page)).length).toBe(3)
  expect((await wizardRequests(page))[2]).toMatchObject({
    wizardId: wizard.wizardId, originSessionId: wizard.originSessionId, followupDone: true,
    answers: [...first.answers, { id: 'layout', question: 'Which layout?', answer: 'Board' }],
  })
  await socketMessage(page, 'agent_app_wizard_finalize', { wizardId: wizard.wizardId, success: true, projectId: 'notes' })
  await expect(dialog).toHaveCount(0)
  expect(await requests(page, 'workflow')).toEqual([])
  expect(await requests(page, 'install')).toEqual([])
})

test('a cancelled chat wizard leaves no creation and a later wizard can still revise its configuration', async ({ page }) => {
  await setup(page)
  const questions = [{ id: 'use', question: 'Choose a use', multiSelect: false, options: ['Personal', 'Work'] }]
  await socketMessage(page, 'agent_app_wizard_open', { wizardId: 'cancelled', config: { name: 'Cancelled app' }, questions })
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(await wizardRequests(page)).toEqual([])
  await socketMessage(page, 'agent_app_wizard_open', { wizardId: 'revised', config: { name: 'Revised app', description: 'Team notes' }, questions })
  const dialog = page.getByRole('dialog', { name: 'Revised app — setup questions', exact: true })
  await dialog.getByRole('button', { name: 'Back', exact: true }).click()
  await expect(dialog.getByPlaceholder('e.g., World News Dashboard', { exact: true })).toHaveValue('Revised app')
  await dialog.getByRole('button', { name: 'Next', exact: true }).click()
  await expect.poll(async () => (await wizardRequests(page, 'agent_app_wizard_interview')).length).toBe(1)
  expect((await wizardRequests(page, 'agent_app_wizard_interview'))[0]).toMatchObject({ wizardId: 'revised', config: { name: 'Revised app' } })
  await socketMessage(page, 'agent_app_wizard_interview', { wizardId: 'revised', success: true, questions })
  await expect(dialog.getByRole('radio', { name: 'Personal', exact: true })).toBeVisible()
  expect(await requests(page, 'workflow')).toEqual([])
  expect(await wizardRequests(page)).toEqual([])
})

test('ZIP import reports upload failures and installs the staged package through Agent-App', async ({ page }) => {
  await setup(page)
  let uploads = 0
  await page.route('**/api/agent-app/import', route => route.fulfill({
    json: ++uploads === 1 ? { success: false, error: 'Invalid package archive' } : { success: true, path: '/staged/notes.zip' },
  }))
  await page.getByRole('button', { name: 'Add Agent App', exact: true }).click()
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  const upload = async () => {
    const chooser = page.waitForEvent('filechooser')
    await page.getByText('Drop a ZIP file here or click to browse', { exact: true }).click()
    await (await chooser).setFiles({ name: 'agentapp_notes_abc123.zip', mimeType: 'application/zip', buffer: Buffer.from('fixture archive') })
  }
  await upload()
  await expect(page.getByRole('alert')).toContainText('Invalid package archive')
  await upload()
  await expect.poll(async () => (await requests(page, 'inspect')).length).toBe(1)
  await expect(page.getByRole('alert')).toHaveCount(0)
  const inspection = (await requests(page, 'inspect'))[0]
  expect(inspection.from).toBe('/staged/notes.zip')
  await reply(page, inspection.requestId, { status: 'success', data: { installable: true } })
  await expect.poll(async () => (await requests(page, 'install')).length).toBe(1)
  const install = (await requests(page, 'install'))[0]
  expect(install.package).toEqual({ from: '/staged/notes.zip' })
  await reply(page, install.requestId, { id: install.requestId, request: install.package, status: 'running', steps: [] })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('Installing app…', { exact: true })).toBeVisible()
  expect(await wizardRequests(page, 'agent_app_import')).toEqual([])
  expect(await requests(page, 'workflow')).toEqual([])
})

test('a pending creation belongs to Agent App and becomes one registered row', async ({ page }, info) => {
  await setup(page)
  const session = { id: 'builder', type: 'agent_app', title: 'Shared notes', createdAt: '2026-11-10', lastActiveAt: '2026-11-10', agentAppFrameworkPending: true }
  await page.evaluate(session => {
    (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [], connected: [] } } });
    (window as any).panelReceive({ type: 'session_list', data: { sessions: [session, { id: 'ordinary', type: 'chat', title: 'Ordinary chat', createdAt: '2026-11-10', lastActiveAt: '2026-11-10' }] } })
  }, session)
  const registry = page.getByRole('region', { name: 'Discovered apps', exact: true })
  await expect(registry.getByRole('button', { name: 'Shared notes', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Shared notes', exact: true })).toHaveCount(1)
  await registry.getByRole('button', { name: 'Shared notes', exact: true }).click()
  await expect(registry.getByRole('button', { name: 'Shared notes', exact: true })).toHaveClass(/agentAppTabActive/)
  await page.screenshot({ path: info.outputPath('pending-app-sidebar.png') })
  await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click()
  await page.getByRole('button', { name: 'Agent App', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Shared notes', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Expand sidebar', exact: true }).click()
  await page.evaluate(session => {
    (window as any).panelReceive({ type: 'session_list', data: { sessions: [{ ...session, agentAppFrameworkPending: false, agentAppFrameworkKey: JSON.stringify(['home', '/apps/shared', 'shared']) }] } });
    (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [{ id: 'shared', name: 'Shared notes', path: '/apps/shared', status: 'stopped' }], connected: [] } } })
  }, session)
  await expect(registry.getByRole('button', { name: 'Open Shared notes', exact: true })).toBeVisible()
  await expect(registry.getByRole('button', { name: 'Shared notes', exact: true })).toHaveCount(0)
  await expect(page.getByText('Shared notes', { exact: true })).toHaveCount(1)
})

test('an unavailable native toolkit reports inspection refusal without starting a conversion agent', async ({ page }) => {
  await setup(page)
  await page.getByRole('button', { name: 'Add Agent App', exact: true }).click()
  await expect.poll(async () => (await requests(page, 'catalogue')).length).toBeGreaterThan(0)
  await reply(page, (await requests(page, 'catalogue')).at(-1).requestId, { status: 'success', data: { apps: [{ id: 'custom-app', name: 'Custom app', description: 'A custom toolkit app' }] } })
  await page.getByRole('dialog').getByRole('button', { name: 'Add', exact: true }).click()
  await expect.poll(async () => (await requests(page, 'inspect')).length).toBe(1)
  await reply(page, (await requests(page, 'inspect'))[0].requestId, { status: 'success', data: { kind: 'agent-app', installable: false, reason: 'The blueprint-custom toolkit is not installed.' } })
  await expect(page.getByRole('dialog')).toContainText('The blueprint-custom toolkit is not installed.')
  expect(await requests(page, 'workflow')).toEqual([])
  expect(await requests(page, 'install')).toEqual([])
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Add', exact: true })).toBeEnabled()
})

test('framework app views retain edits across navigation and never receive a legacy theme', async ({ page }) => {
  await setup(page)
  const app = { id: 'framework-notes', name: 'Framework notes', path: '/framework/notes', status: 'running' }
  await page.evaluate(app => (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [app], connected: [] } } }), app)
  const open = async () => {
    await page.getByRole('button', { name: 'Open Framework notes', exact: true }).click()
    await expect.poll(() => page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_open').length)).toBeGreaterThan(0)
    const request = await page.evaluate(() => (window as any).panelRequests.filter((r: any) => r.type === 'agent_app_framework_open').at(-1))
    await page.evaluate(({ request, app }) => (window as any).panelReceive({ type: 'agent_app_framework_open', data: { requestId: request.requestId, status: 'success', data: { id: app.id, path: app.path, name: app.name, url: 'http://localhost:7935/tests/fixtures/panel-app.html' } } }), { request, app })
  }
  await open()
  const frame = page.frameLocator('iframe[data-framework]')
  await frame.getByRole('textbox', { name: 'App note' }).fill('Keep my changes')
  await page.getByRole('button', { name: 'Back to chat', exact: true }).click()
  await expect(page.locator('iframe[data-framework]')).toBeHidden()
  await open()
  await expect(frame.getByRole('textbox', { name: 'App note' })).toHaveValue('Keep my changes')
  await expect(frame.locator('#theme')).toHaveText('Waiting for theme')
})

test('startup preference stays in Settings without exposing management or migration screens', async ({ page }) => {
  await setup(page)
  const app = { id: 'native', name: 'Native board', path: '/apps/native', status: 'stopped' }
  await page.evaluate(app => {
    (window as any).frameworkState.inventory = { legacy: [{ id: 'old-board', name: 'Old board', reason: 'Preserve source and verify replacement first.' }], migrations: [] };
    (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: [app], connected: [] } } })
  }, app)
  await page.getByRole('button', { name: 'Open Native board', exact: true }).click()
  await openFrameworkSettings(page, 'Native board')
  await page.getByLabel('Auto-launch on startup').click()
  await expect.poll(async () => (await requests(page, 'preference')).length).toBe(1)
  const preference = (await requests(page, 'preference'))[0]
  expect(preference).toMatchObject({ path: app.path, appId: app.id, autoStart: true })
  await reply(page, preference.requestId, { ...app, appId: app.id, autoStart: true, sessionId: 'dest' })
  await expect(page.getByLabel('Auto-launch on startup')).toBeChecked()
  expect(await requests(page, 'workflow')).toEqual([])
  await expect(page.getByRole('button', { name: 'App activity and migration', exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Install activity', exact: true })).toHaveCount(0)
})

test('the original import tab installs a compatible source and keeps inspection failures visible', async ({ page }, info) => {
  await setup(page)
  await page.getByRole('button', { name: 'Add Agent App', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Add Agent App', exact: true })
  await dialog.getByRole('button', { name: 'Import', exact: true }).click()
  const source = dialog.locator('#agent-app-import-source')
  await source.fill('/packages/notes.zip')
  const importButton = dialog.getByRole('button', { name: 'Import App', exact: true })
  await importButton.click()
  await expect.poll(async () => (await requests(page, 'inspect')).length).toBe(1)
  const inspect = (await requests(page, 'inspect'))[0]
  expect(inspect.from).toBe('/packages/notes.zip')
  await reply(page, inspect.requestId, { status: 'error', stderr: 'Package is unreadable.' })
  await expect(dialog.getByRole('alert')).toContainText('Package is unreadable.')
  expect(await requests(page, 'install')).toEqual([])
  await importButton.click()
  await expect.poll(async () => (await requests(page, 'inspect')).length).toBe(2)
  await reply(page, (await requests(page, 'inspect'))[1].requestId, { status: 'success', data: { installable: true } })
  await expect.poll(async () => (await requests(page, 'install')).length).toBe(1)
  expect((await requests(page, 'install'))[0].package).toEqual({ from: '/packages/notes.zip' })
  expect(await requests(page, 'workflow')).toEqual([])
  await dialog.screenshot({ path: info.outputPath('original-import-dialog.png') })
})

test('registry app settings use the original settings page and preserve path-scoped identity', async ({ page }, info) => {
  await setup(page)
  const apps = [
    { id: 'same', name: 'Board one', path: '/apps/one', status: 'running' },
    { id: 'same', name: 'Board two', path: '/apps/two', status: 'stopped' },
  ]
  await page.evaluate(apps => (window as any).panelReceive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps, connected: [] } } }), apps)
  await openFrameworkSettings(page, 'Board two')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const card = page.getByRole('article', { name: 'Board two settings' })
  await expect(card.getByText('/apps/two', { exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: 'Board one settings' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Agent App', exact: true })).toBeVisible()
  await card.getByLabel('Auto-launch on startup').click()
  await expect.poll(async () => (await requests(page, 'preference')).length).toBe(1)
  const request = (await requests(page, 'preference'))[0]
  expect(request).toMatchObject({ path: '/apps/two', appId: 'same', autoStart: true })
  await reply(page, request.requestId, { path: '/apps/two', appId: 'same', autoStart: true, sessionId: 'dest' })
  await page.screenshot({ path: info.outputPath('original-settings-page.png') })
})
