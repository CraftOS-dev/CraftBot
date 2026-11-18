import { describe, expect, it } from 'vitest'
import type { FrameworkLifecycleResult } from '../../../browser/frontend/src/types'
import type { FrameworkAttachment, RegistryApp } from '../../src/apps/framework'
import {
  FRESH_STATE,
  adjustStep,
  asInterval,
  buildRows,
  clampKeep,
  cycleInterval,
  isSelectable,
  layoutLines,
  selectedIndex,
  triggerLabel,
  type Item,
  type PanelState,
  type Tr,
} from '../../src/screens/apps/AppSettingsPanel'

// Keys stand in for the strings; options are shown so tests can read them.
const t: Tr = (key, options) => (options && Object.keys(options).length ? `${key}${JSON.stringify(options)}` : key)
const when = (ms: number) => `@${ms}`

const local: RegistryApp = { id: 'notes', name: 'Notes', path: 'C:/apps/notes', status: 'running', port: 3101, url: 'http://127.0.0.1:3101' }
const remote: RegistryApp = {
  id: 'crm',
  name: 'CRM',
  path: 'connection:abc',
  status: 'running',
  connection: { appId: 'crm', name: 'CRM', origin: 'https://crm.example.com', credentialId: null, principalName: 'Ada', principal: 'ada@example.com', status: 'online' },
}
const attachment: FrameworkAttachment = {
  key: 'k',
  path: local.path,
  appId: local.id,
  name: local.name,
  sessionId: 's1',
  tasksAllowed: true,
  ownerToolsAllowed: false,
  autoStart: true,
  logCleanup: false,
  backupsEnabled: true,
  backupInterval: '6h',
  backupKeep: 99,
}
const loaded: PanelState = {
  ...FRESH_STATE,
  loaded: true,
  attachment,
  details: { capabilities: { declared: { summarize: { description: 'Summarize a note' }, tag: {} } } },
  maintenance: {
    port: 3101,
    backups: [
      { filename: 'b2.zip', ts: 2000, size: 2048, trigger: 'scheduled' },
      { filename: 'b1.zip', ts: 1000, size: 1024, trigger: 'pre-remove' },
    ],
    backupStatus: { lastAt: 2, count: 2, totalSize: 3072, lastError: null },
    backupSupport: { mode: 'cli' },
  },
  links: { lan: 'http://192.168.1.2:4000/?a2app_share=x' },
}

const rows = (app: RegistryApp, state: PanelState, extra: { connected?: boolean; fresh?: boolean; job?: FrameworkLifecycleResult } = {}) =>
  buildRows(t, { app, state, connected: extra.connected ?? true, fresh: extra.fresh ?? true, job: extra.job, when })
const ids = (items: Item[]) => items.filter(isSelectable).map(item => item.id)
const find = (items: Item[], id: string) => items.find(item => item.id === id)

describe('backup values', () => {
  it('keeps between 1 and 30 backups', () => {
    expect(clampKeep(0)).toBe(1)
    expect(clampKeep(7)).toBe(7)
    expect(clampKeep(31)).toBe(30)
    expect(clampKeep(4.6)).toBe(5)
    expect(clampKeep(Number.NaN)).toBe(7)
  })

  it('cycles the frequency and wraps at the ends', () => {
    expect(cycleInterval('hourly', -1)).toBe('weekly')
    expect(cycleInterval('weekly', 1)).toBe('hourly')
    expect(cycleInterval('daily', 1)).toBe('weekly')
    expect(cycleInterval('nonsense', 1)).toBe('weekly')
    expect(asInterval('6h')).toBe('6h')
    expect(asInterval(undefined)).toBe('daily')
  })

  it('steps an open adjuster', () => {
    expect(adjustStep({ setting: 'backupKeep', value: 30 }, 1)).toEqual({ setting: 'backupKeep', value: 30 })
    expect(adjustStep({ setting: 'backupKeep', value: 2 }, -1)).toEqual({ setting: 'backupKeep', value: 1 })
    expect(adjustStep({ setting: 'backupInterval', value: 'daily' }, -1)).toEqual({ setting: 'backupInterval', value: '6h' })
  })

  it('names backup triggers, old and new spellings alike', () => {
    expect(triggerLabel(t, 'pre-remove')).toBe('backups.trigger.preRemove')
    expect(triggerLabel(t, 'pre_delete')).toBe('backups.trigger.preRemove')
    expect(triggerLabel(t, undefined)).toBe('backups.trigger.manual')
    expect(triggerLabel(t, 'custom')).toBe('custom')
  })
})

describe('panel rows', () => {
  it('shows every section of a running local app, in order', () => {
    const items = rows(local, loaded)
    expect(ids(items)).toEqual([
      'path',
      'url',
      'lifecycle',
      'autoStart',
      'logCleanup',
      'allow',
      'requests',
      'ownerTools',
      'backupsEnabled',
      'interval',
      'keep',
      'backupNow',
      'b-b2.zip',
      'b-b1.zip',
      'share-lan',
      'share-tunnel',
      'theme',
      'export',
      'remove',
    ])
    expect(find(items, 'lifecycle')).toMatchObject({ label: 'lifecycle.stop' })
    expect(find(items, 'keep')).toMatchObject({ value: 30 })
    expect(find(items, 'interval')).toMatchObject({ value: '6h' })
    expect(find(items, 'share-lan')).toMatchObject({ link: loaded.links.lan })
    expect(find(items, 'share-tunnel')).toMatchObject({ link: null })
    expect(find(items, 'remove')).toMatchObject({ label: 'remove.delete', danger: true })
    expect(find(items, 'requests')).toMatchObject({ label: 'requests.view{"count":2}' })
    expect(items.filter(isSelectable).every(item => !('reason' in item) || !item.reason || item.id === 'ownerTools')).toBe(true)
  })

  it('needs requests allowed before owner access', () => {
    const items = rows(local, { ...loaded, attachment: { ...attachment, tasksAllowed: false } })
    expect(find(items, 'ownerTools')).toMatchObject({ reason: 'requests.needsAllow' })
    expect(find(rows(local, loaded), 'ownerTools')).toMatchObject({ reason: undefined })
  })

  it('lists the declared requests while open', () => {
    const items = rows(local, { ...loaded, requestsOpen: true })
    expect(find(items, 'requests')).toMatchObject({ label: 'requests.hide' })
    expect(find(items, 'req-summarize')).toMatchObject({ kind: 'note', text: 'Summarize a note', bullet: true })
    expect(find(items, 'req-tag')).toMatchObject({ kind: 'note', text: 'tag' })
  })

  it('blocks every change while disconnected, but not showing the requests', () => {
    const items = rows(local, loaded, { connected: false })
    for (const item of items.filter(isSelectable)) {
      if (item.kind === 'copy' || item.id === 'requests') continue
      expect(item, item.id).toMatchObject({ reason: 'panel.disconnected' })
    }
    expect(find(items, 'offline')).toMatchObject({ kind: 'note', tone: 'warn' })
  })

  it('blocks changes while another action runs', () => {
    const items = rows(local, { ...loaded, running: 'backup' })
    expect(find(items, 'backupNow')).toMatchObject({ busy: true, reason: 'common.busy' })
    expect(find(items, 'autoStart')).toMatchObject({ reason: 'common.busy' })
    expect(find(items, 'remove')).toMatchObject({ reason: 'common.busy' })
  })

  it('waits for the host before switching anything', () => {
    const items = rows(local, { ...FRESH_STATE })
    expect(find(items, 'loading')).toMatchObject({ kind: 'note' })
    expect(find(items, 'autoStart')).toMatchObject({ value: true, reason: 'common.notReady' })
    expect(find(items, 'backupNow')).toMatchObject({ reason: 'common.notReady' })
  })

  it('says why backups are unavailable', () => {
    const state = { ...loaded, maintenance: { ...loaded.maintenance!, backupSupport: { mode: null, reason: 'No data folder' } } }
    const items = rows(local, state)
    expect(find(items, 'backupSupport')).toMatchObject({ text: 'No data folder' })
    expect(find(items, 'backupNow')).toMatchObject({ reason: 'No data folder' })
    expect(find(items, 'b-b1.zip')).toMatchObject({ reason: 'No data folder' })
  })

  it('offers a retry when the backup list failed', () => {
    const items = rows(local, { ...loaded, maintenanceError: 'boom' })
    expect(find(items, 'maintenanceError')).toMatchObject({ text: 'backups.loadFailed{"error":"boom"}', tone: 'error' })
    expect(find(items, 'retry')).toMatchObject({ kind: 'action' })
  })

  it('shows the lifecycle in progress and its feedback', () => {
    const job: FrameworkLifecycleResult = { requestId: 'r', path: local.path, appId: local.id, operation: 'start', status: 'running', message: 'Building' }
    const items = rows({ ...local, status: 'stopped' }, loaded, { job })
    expect(find(items, 'status')).toMatchObject({ value: 'status.starting' })
    expect(find(items, 'lifecycle')).toMatchObject({ label: 'status.starting', reason: 'lifecycle.busy' })
    expect(find(items, 'jobMessage')).toMatchObject({ text: 'Building' })
    expect(find(items, 'remove')).toMatchObject({ reason: 'lifecycle.busy' })
    const stopped = rows(local, loaded, { job: { ...job, operation: 'stop', status: 'success', remaining: true } })
    expect(find(stopped, 'jobRemaining')).toMatchObject({ text: 'lifecycle.remaining' })
    const lost = rows(local, loaded, { job: { ...job, status: 'unknown' } })
    expect(find(lost, 'jobUnknown')).toBeTruthy()
  })

  it('hides sharing while stopped and start/stop for apps it cannot change', () => {
    const stopped = rows({ ...local, status: 'stopped' }, loaded)
    expect(ids(stopped)).not.toContain('share-lan')
    expect(find(stopped, 'lifecycle')).toMatchObject({ label: 'lifecycle.start' })
    expect(ids(rows({ ...local, status: 'unreachable' }, loaded))).not.toContain('lifecycle')
  })

  it('keeps a missing app to its header and removal', () => {
    const items = rows({ ...local, status: 'missing' }, loaded)
    expect(ids(items)).toEqual(['path', 'url', 'remove'])
    expect(find(items, 'remove')).toMatchObject({ label: 'remove.forget' })
  })

  it('shows a connected app with its origin and account, and only what it can change', () => {
    const items = rows(remote, { ...loaded, attachment: { ...attachment, tasksAllowed: false } })
    expect(find(items, 'origin')).toMatchObject({ value: 'https://crm.example.com' })
    expect(find(items, 'account')).toMatchObject({ value: 'Ada' })
    expect(find(items, 'connection')).toMatchObject({ value: 'connectionStatus.online{"defaultValue":"online"}', tone: 'success' })
    expect(ids(items)).toEqual(['path', 'allow', 'requests', 'theme', 'remove'])
    expect(find(items, 'remove')).toMatchObject({ label: 'remove.disconnect' })
  })

  it('refuses start, stop and removal while the app list is stale', () => {
    const items = rows(local, loaded, { fresh: false })
    expect(find(items, 'lifecycle')).toMatchObject({ reason: 'common.listStale' })
    expect(find(items, 'remove')).toMatchObject({ reason: 'common.listStale' })
  })

  it('shows the exported file as a copy row', () => {
    const items = rows(local, { ...loaded, exportFile: 'C:/exports/notes.zip' })
    expect(find(items, 'exportFile')).toMatchObject({ kind: 'copy', value: 'C:/exports/notes.zip', open: false })
  })

  it('keeps the selected row when rows above it come and go', () => {
    const running = rows(local, loaded).filter(isSelectable)
    const stopped = rows({ ...local, status: 'stopped', url: null }, loaded).filter(isSelectable)
    const at = running.findIndex(item => item.id === 'lifecycle')
    expect(selectedIndex(running, { index: at, selectedId: 'lifecycle' })).toBe(at)
    expect(stopped[selectedIndex(stopped, { index: at, selectedId: 'lifecycle' })].id).toBe('lifecycle')
    // A row that went away leaves the selection at the same position.
    expect(selectedIndex(stopped, { index: 1, selectedId: 'url' })).toBe(1)
    expect(selectedIndex(stopped, { index: 99, selectedId: null })).toBe(stopped.length - 1)
    expect(selectedIndex([], { index: 3, selectedId: 'x' })).toBe(0)
  })

  it('wraps long notes into display lines', () => {
    const items: Item[] = [
      { kind: 'heading', id: 'h', label: 'H' },
      { kind: 'note', id: 'n', text: 'one two three four five six seven eight nine ten' },
    ]
    const lines = layoutLines(items, 20)
    expect(lines[0].item.id).toBe('h')
    expect(lines.length).toBeGreaterThan(2)
    expect(lines.slice(1).every(line => line.item.id === 'n')).toBe(true)
    expect(lines.slice(1).map(line => line.text).join(' ')).toBe('one two three four five six seven eight nine ten')
  })
})
