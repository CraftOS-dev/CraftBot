/**
 * One Agent App's settings as a keyboard panel, the same settings the
 * browser shows on an app's settings card (FrameworkAppActions,
 * FrameworkMaintenanceControls, FrameworkAppControls, FrameworkAppDialogs):
 *
 *   header      name, status, port, path (copy), address (copy, open); for a
 *               connected app its origin, account and connection state
 *   run         Start or Stop (local apps that are running or stopped), with
 *               the lifecycle feedback of the host
 *   preferences start automatically, clean logs on start (local apps)
 *   requests    allow requests, the declared requests, owner access to local
 *               tools (local apps)
 *   backups     schedule, frequency, keep count, back up now, the archive
 *               list with restore and delete (local apps)
 *   share       LAN and public links (running local apps)
 *   appearance  the theme pack
 *   package     export the app as a package file (local apps)
 *   remove      delete, remove from the list, or disconnect
 *
 * Every change goes over the host's request channel (`frameworkRequest`) or
 * the lifecycle message, exactly as the browser sends it.
 *
 * API (AppsScreen, AppScreen and the Settings tab use exactly this):
 *
 *   <AppSettingsPanel app columns rows active onDeleted? />
 *     Renders at most `rows` lines of `columns` cells. The last line holds
 *     the panel's own key hints.
 *
 *   const panelKey = useAppSettingsKeys(app, onDeleted?)
 *     A hook: call it during render, then call `panelKey(input, key)` first
 *     while the panel is shown. It returns true for keys it used. It never
 *     takes Tab, '[', ']' or 'q', and Esc or Left only while something is
 *     open (a confirmation, the theme picker or a value being changed), which
 *     takes every key until it closes.
 *
 * Keys: j/k or arrows move, Enter or Space acts on the row (switch, run,
 * change, choose, create a link), c copies, o opens with the system's
 * default app, r restores a backup, x deletes a backup or closes a link.
 *
 * The hook and the component render separately, so the state they share
 * (selection, open editors, loaded data) lives in a module store keyed by
 * frameworkAppKey(path, id).
 */
import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react'
import { Box, Text, type Key } from 'ink'
import { useTranslation } from 'react-i18next'
import i18next from 'i18next'
import type { FrameworkLifecycleResult } from '../../../../browser/frontend/src/types'
import { formatDateTime } from '../../../../browser/frontend/src/i18n/format'
import { useAppDispatch, useAppSelector } from '../../state/hooks'
import type { AppDispatch } from '../../state/store'
import { pushToast } from '../../state/tuiSlice'
import {
  appPhase,
  canChangeState,
  changeAppState,
  errorText,
  frameworkAppKey,
  frameworkRequest,
  requestAppList,
  type AppPhase,
  type FrameworkAttachment,
  type RegistryApp,
} from '../../apps/framework'
import { removeApp, removalKind } from '../../apps/removal'
import {
  applyTheme,
  appThemeId,
  openThemePicker,
  pickerListHeight,
  themeDescription,
  themeName,
  themePickerKey,
  ThemePicker,
  type ThemePickerState,
} from './hostThemes'
import { copyToClipboard } from '../settings/connectClipboard'
import { openExternal } from '../settings/connectOpen'
import { Pointer, rowStyle } from '../../ui/selection'
import { useTicker } from '../../ui/useTicker'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { padEnd, truncate, width as cells, wrap } from '../../text/width'

/** A translate function (keys of the appsSettings namespace, or namespaced keys). */
export type Tr = (key: string, options?: Record<string, unknown>) => string

const tr: Tr = (key, options) => i18next.t(`appsSettings:${key}`, options ?? {})

// --- host data ---------------------------------------------------------------

export type ShareChannel = 'lan' | 'tunnel'
export const SHARE_CHANNELS: readonly ShareChannel[] = ['lan', 'tunnel']
export type Links = Partial<Record<ShareChannel, string | null>>

export const BACKUP_INTERVALS = ['hourly', '6h', 'daily', 'weekly'] as const
export type BackupInterval = (typeof BACKUP_INTERVALS)[number]

export interface BackupEntry {
  filename: string
  /** Milliseconds since the epoch. */
  ts: number
  size: number
  trigger?: string
}

export interface MaintenanceInfo {
  port?: number | null
  backups: BackupEntry[]
  backupStatus?: { lastAt?: number | null; lastError?: string | null; count?: number; totalSize?: number }
  links?: Links
  backupSupport?: { mode: string | null; reason?: string } | null
}

export interface AppDetails {
  capabilities?: { declared?: Record<string, { description?: string } | null> }
}

interface CommandResult {
  status: string
  stderr?: string
  data?: { ok?: boolean; file?: string; path?: string; url?: string; backup?: string }
}

// --- pure helpers ------------------------------------------------------------

/** "3.1 MB" style sizes. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** The host keeps between 1 and 30 scheduled backups. */
export function clampKeep(value: number): number {
  if (!Number.isFinite(value)) return 7
  return Math.min(30, Math.max(1, Math.round(value)))
}

/** The next backup frequency, wrapping at the ends. */
export function cycleInterval(current: string, delta: -1 | 1): BackupInterval {
  const at = BACKUP_INTERVALS.indexOf(current as BackupInterval)
  const n = BACKUP_INTERVALS.length
  return BACKUP_INTERVALS[((at < 0 ? BACKUP_INTERVALS.indexOf('daily') : at) + delta + n) % n]
}

export function asInterval(value: unknown): BackupInterval {
  return BACKUP_INTERVALS.includes(value as BackupInterval) ? (value as BackupInterval) : 'daily'
}

const TRIGGER_KEYS: Record<string, string> = {
  scheduled: 'scheduled',
  manual: 'manual',
  'pre-remove': 'preRemove',
  pre_delete: 'preRemove',
  'pre-promote': 'preUpdate',
  pre_promote: 'preUpdate',
  'pre-restore': 'preRestore',
  pre_restore: 'preRestore',
}

/** What made a backup, in words; an unknown trigger reads as itself. */
export function triggerLabel(t: Tr, trigger: string | undefined): string {
  const key = TRIGGER_KEYS[trigger ?? 'manual']
  return key ? t(`backups.trigger.${key}`) : String(trigger)
}

// --- the panel's state -------------------------------------------------------

type Tone = 'info' | 'success' | 'error' | 'warn' | 'muted'

interface Flash {
  tone: Tone
  text: string
}

interface PanelConfirm {
  message: string
  run: () => void
}

export type Adjust = { setting: 'backupInterval'; value: BackupInterval } | { setting: 'backupKeep'; value: number }

/** What the host told us about the app. */
export interface PanelData {
  /** The host snapshot answered (the attachment may still be absent: never attached). */
  loaded: boolean
  attachment?: FrameworkAttachment
  details: AppDetails | null
  maintenance: MaintenanceInfo | null
  maintenanceError: string
  links: Links
  loadError: string
}

export interface PanelState extends PanelData {
  /** The selected row: its id, and its index for when that row goes away. */
  selectedId: string | null
  index: number
  confirm: PanelConfirm | null
  picker: ThemePickerState | null
  adjust: Adjust | null
  requestsOpen: boolean
  /** A one-off message (an outcome, copied), cleared by the next key. */
  flash: Flash | null
  /** The action now running (one at a time, as in the browser). */
  running: string | null
  pendingShare: ShareChannel | null
  shareError: { channel: ShareChannel; message: string } | null
  restoring: boolean
  /** The file of the last export. */
  exportFile: string | null
}

export const FRESH_STATE: PanelState = {
  loaded: false,
  details: null,
  maintenance: null,
  maintenanceError: '',
  links: {},
  loadError: '',
  selectedId: null,
  index: 0,
  confirm: null,
  picker: null,
  adjust: null,
  requestsOpen: false,
  flash: null,
  running: null,
  pendingShare: null,
  shareError: null,
  restoring: false,
  exportFile: null,
}

const states = new Map<string, PanelState>()
const listeners = new Set<() => void>()
/** Not rendered: the request guard, a version that makes stale refreshes drop, the layout sizes. */
const meta = new Map<string, { pending: boolean; version: number; listHeight: number; pickerRows: number }>()
/** The latest onDeleted of whoever shows the panel for an app. */
const onDeletedByKey = new Map<string, () => void>()

function getState(appKey: string): PanelState {
  if (!appKey) return FRESH_STATE
  let state = states.get(appKey)
  if (!state) {
    state = FRESH_STATE
    states.set(appKey, state)
  }
  return state
}

function setState(appKey: string, patch: Partial<PanelState> | ((state: PanelState) => Partial<PanelState>)): void {
  if (!appKey) return
  const state = getState(appKey)
  states.set(appKey, { ...state, ...(typeof patch === 'function' ? patch(state) : patch) })
  listeners.forEach(listener => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function metaOf(appKey: string) {
  let entry = meta.get(appKey)
  if (!entry) {
    entry = { pending: false, version: 0, listHeight: 10, pickerRows: 12 }
    meta.set(appKey, entry)
  }
  return entry
}

function usePanelState(appKey: string): PanelState {
  return useSyncExternalStore(subscribe, () => getState(appKey), () => getState(appKey))
}

// --- rows --------------------------------------------------------------------

export type ToggleId = 'autoStart' | 'logCleanup' | 'allow' | 'ownerTools' | 'backupsEnabled'
export type ActionId = 'lifecycle' | 'requests' | 'retry' | 'backupNow' | 'export' | 'remove'

/** One row of the panel. `reason` set: the row cannot act now, and says why. */
export type Item =
  | { kind: 'heading'; id: string; label: string }
  | { kind: 'info'; id: string; label: string; value: string; tone?: Tone }
  | { kind: 'note'; id: string; text: string; tone?: Tone; bullet?: boolean }
  | { kind: 'copy'; id: 'path' | 'url' | 'exportFile'; label: string; value: string; desc: string; open: boolean }
  | { kind: 'toggle'; id: ToggleId; label: string; desc: string; value: boolean; busy?: boolean; reason?: string }
  | { kind: 'action'; id: ActionId; label: string; desc: string; value?: string; busy?: boolean; reason?: string; danger?: boolean }
  | { kind: 'interval'; id: 'interval'; label: string; desc: string; value: BackupInterval; busy?: boolean; reason?: string }
  | { kind: 'keep'; id: 'keep'; label: string; desc: string; value: number; busy?: boolean; reason?: string }
  | { kind: 'theme'; id: 'theme'; label: string; desc: string; themeId: string; busy?: boolean; reason?: string }
  | { kind: 'backup'; id: string; entry: BackupEntry; reason?: string }
  | { kind: 'share'; id: string; channel: ShareChannel; link: string | null; busy?: boolean; reason?: string }

export type SelectableItem = Exclude<Item, { kind: 'heading' | 'info' | 'note' }>

/** The selected row: by id while that row exists (rows come and go), else by position. */
export function selectedIndex(selectable: SelectableItem[], state: Pick<PanelState, 'index' | 'selectedId'>): number {
  if (selectable.length === 0) return 0
  const byId = state.selectedId ? selectable.findIndex(item => item.id === state.selectedId) : -1
  return byId >= 0 ? byId : Math.min(state.index, selectable.length - 1)
}

export function isSelectable(item: Item): item is SelectableItem {
  return item.kind !== 'heading' && item.kind !== 'info' && item.kind !== 'note'
}

const PHASE_TONE: Record<AppPhase, Tone> = {
  running: 'success',
  starting: 'warn',
  stopping: 'warn',
  stopped: 'muted',
  missing: 'warn',
  unreachable: 'error',
}

export interface RowsInput {
  app: RegistryApp
  job: FrameworkLifecycleResult | undefined
  connected: boolean
  /** The registry list is current (the browser's `fresh`). */
  fresh: boolean
  /** The app is no longer in a current registry list. */
  gone?: boolean
  state: PanelState
  /** Date formatting (milliseconds since the epoch). */
  when?: (ms: number) => string
}

/** Every row the panel shows for an app, in order. Pure: the panel and its tests use it. */
export function buildRows(t: Tr, input: RowsInput): Item[] {
  const { app, job, connected, fresh, state } = input
  const when = input.when ?? ((ms: number) => formatDateTime(new Date(ms)))
  const sep = ` ${glyphs().sep} `
  const items: Item[] = []
  const remote = !!app.connection
  const phase = appPhase(app, job)
  const lifecycleBusy = job?.status === 'running'
  const busy = state.running !== null

  // Why a row cannot act right now, most important first.
  const offline = connected ? undefined : t('panel.disconnected')
  const blocked = offline ?? (busy ? t('common.busy') : undefined)
  const unloaded = blocked ?? (state.loaded ? undefined : t('common.notReady'))

  items.push({ kind: 'info', id: 'name', label: t('panel.name'), value: app.name })
  items.push({ kind: 'info', id: 'status', label: t('panel.status'), value: t(`status.${phase}`), tone: PHASE_TONE[phase] })
  if (input.gone) {
    items.push({ kind: 'note', id: 'gone', text: t('panel.gone'), tone: 'muted' })
    return items
  }
  if (app.connection) {
    const c = app.connection
    items.push({ kind: 'info', id: 'origin', label: t('panel.origin'), value: c.origin })
    items.push({ kind: 'info', id: 'account', label: t('panel.signedInAs'), value: c.principalName || c.principal })
    items.push({
      kind: 'info',
      id: 'connection',
      label: t('panel.connection'),
      value: t(`connectionStatus.${c.status}`, { defaultValue: c.status }),
      tone: c.status === 'online' ? 'success' : c.status === 'offline' ? 'muted' : 'error',
    })
  } else {
    const port = app.port ?? state.maintenance?.port
    items.push({ kind: 'info', id: 'port', label: t('panel.port'), value: port != null ? String(port) : '-' })
  }
  items.push({ kind: 'copy', id: 'path', label: t('panel.path'), value: app.path, desc: t('panel.pathDesc'), open: false })
  if (app.url) items.push({ kind: 'copy', id: 'url', label: t('panel.address'), value: app.url, desc: t('panel.addressDesc'), open: true })
  if (!connected) items.push({ kind: 'note', id: 'offline', text: t('panel.disconnected'), tone: 'warn' })
  if (state.loadError) items.push({ kind: 'note', id: 'loadError', text: state.loadError, tone: 'error' })

  // Start or stop, with what the host said about the last one.
  if (!remote && (canChangeState(app) || lifecycleBusy)) {
    const operation = lifecycleBusy && job ? job.operation : app.status === 'running' ? 'stop' : 'start'
    items.push({
      kind: 'action',
      id: 'lifecycle',
      label: t(lifecycleBusy ? (operation === 'start' ? 'status.starting' : 'status.stopping') : `lifecycle.${operation}`),
      desc: t(operation === 'start' ? 'lifecycle.startDesc' : 'lifecycle.stopDesc'),
      reason: offline ?? (!fresh ? t('common.listStale') : lifecycleBusy ? t('lifecycle.busy') : undefined),
    })
  }
  if (job) {
    if (lifecycleBusy && job.message) items.push({ kind: 'note', id: 'jobMessage', text: job.message, tone: 'info' })
    if (job.status === 'error') items.push({ kind: 'note', id: 'jobError', text: job.message || t('lifecycle.failed'), tone: 'error' })
    if (job.status === 'unknown') items.push({ kind: 'note', id: 'jobUnknown', text: t('lifecycle.unknown'), tone: 'warn' })
    if (job.remaining && job.operation === 'stop' && job.status !== 'running') {
      items.push({ kind: 'note', id: 'jobRemaining', text: t('lifecycle.remaining'), tone: 'muted' })
    }
  }

  const pushRemove = () => {
    const kind = removalKind(app, false)
    items.push({ kind: 'heading', id: 'h-remove', label: t('sections.remove') })
    items.push({
      kind: 'action',
      id: 'remove',
      label: t(kind === 'disconnect' ? 'remove.disconnect' : kind === 'forget' ? 'remove.forget' : 'remove.delete'),
      desc: t(kind === 'disconnect' ? 'remove.disconnectDesc' : kind === 'forget' ? 'remove.forgetDesc' : 'remove.deleteDesc'),
      value: state.running === 'remove' ? t('panel.working') : undefined,
      busy: state.running === 'remove',
      reason: offline ?? (!fresh ? t('common.listStale') : lifecycleBusy ? t('lifecycle.busy') : busy ? t('common.busy') : undefined),
      danger: true,
    })
  }

  // A missing app has nothing to load: it can only leave the list.
  if (app.status === 'missing') {
    pushRemove()
    return items
  }
  if (connected && !state.loaded && !state.loadError) items.push({ kind: 'note', id: 'loading', text: t('panel.loading'), tone: 'muted' })

  const working = (id: string) => (state.running === id ? { value: t('panel.working'), busy: true } : {})
  const toggle = (id: ToggleId, label: string, desc: string, value: boolean, reason: string | undefined) =>
    items.push({ kind: 'toggle', id, label, desc, value, busy: state.running === `toggle:${id}`, reason })

  if (!remote) {
    items.push({ kind: 'heading', id: 'h-prefs', label: t('sections.preferences') })
    toggle('autoStart', t('prefs.autoStart'), t('prefs.autoStartDesc'), state.attachment?.autoStart !== false, unloaded)
    toggle('logCleanup', t('prefs.logCleanup'), t('prefs.logCleanupDesc'), state.attachment?.logCleanup === true, unloaded)
    if (state.attachment?.startError) items.push({ kind: 'note', id: 'startError', text: state.attachment.startError, tone: 'error' })
  }

  items.push({ kind: 'heading', id: 'h-requests', label: t('sections.requests') })
  const allowed = state.attachment?.tasksAllowed === true
  const noDetails = state.details ? undefined : t('common.notReady')
  toggle('allow', t('requests.allow'), t('requests.allowDesc'), allowed, unloaded ?? noDetails)
  const declared = Object.entries(state.details?.capabilities?.declared ?? {})
  if (declared.length > 0) {
    items.push({
      kind: 'action',
      id: 'requests',
      label: state.requestsOpen ? t('requests.hide') : t('requests.view', { count: declared.length }),
      desc: t('requests.listDesc'),
    })
    if (state.requestsOpen) {
      for (const [name, capability] of declared) {
        items.push({ kind: 'note', id: `req-${name}`, text: capability?.description || name, bullet: true })
      }
    }
  }
  if (!remote) {
    toggle(
      'ownerTools',
      t('requests.ownerTools'),
      t('requests.ownerToolsDesc'),
      state.attachment?.ownerToolsAllowed === true,
      unloaded ?? noDetails ?? (allowed ? undefined : t('requests.needsAllow')),
    )
  }
  if (state.attachment?.bridgeError) items.push({ kind: 'note', id: 'bridgeError', text: state.attachment.bridgeError, tone: 'error' })

  if (!remote) {
    items.push({ kind: 'heading', id: 'h-backups', label: t('sections.backups') })
    const m = state.maintenance
    if (state.maintenanceError) {
      items.push({ kind: 'note', id: 'maintenanceError', text: t('backups.loadFailed', { error: state.maintenanceError }), tone: 'error' })
      items.push({ kind: 'action', id: 'retry', label: t('backups.retry'), desc: t('backups.retryDesc'), ...working('retry'), reason: blocked })
    }
    if (m?.backupSupport?.reason) items.push({ kind: 'note', id: 'backupSupport', text: m.backupSupport.reason, tone: 'muted' })
    const unsupported = m?.backupSupport?.mode === null ? m.backupSupport.reason || t('common.notReady') : undefined
    const backupReason = unloaded ?? (m ? unsupported : t('common.notReady'))
    const enabled = state.attachment?.backupsEnabled === true
    toggle('backupsEnabled', t('backups.scheduled'), t('backups.scheduledDesc'), enabled, backupReason)
    if (enabled) {
      items.push({
        kind: 'interval',
        id: 'interval',
        label: t('backups.frequency'),
        desc: t('backups.frequencyDesc'),
        value: asInterval(state.attachment?.backupInterval),
        busy: state.running === 'adjust:interval',
        reason: backupReason,
      })
      items.push({
        kind: 'keep',
        id: 'keep',
        label: t('backups.keep'),
        desc: t('backups.keepDesc'),
        value: clampKeep(state.attachment?.backupKeep || 7),
        busy: state.running === 'adjust:keep',
        reason: backupReason,
      })
    }
    if (m) {
      const status = m.backupStatus ?? {}
      const text = status.lastError
        ? t('backups.lastFailed', { error: status.lastError })
        : status.lastAt
          ? [t('backups.last', { when: when(status.lastAt * 1000) }), t('backups.kept', { count: status.count ?? 0 }), formatBytes(status.totalSize ?? 0)].join(sep)
          : t('backups.none')
      items.push({ kind: 'note', id: 'backupStatus', text, tone: status.lastError ? 'error' : 'muted' })
    }
    items.push({ kind: 'action', id: 'backupNow', label: t('backups.now'), desc: t('backups.nowDesc'), ...working('backup'), reason: backupReason })
    if (state.restoring) items.push({ kind: 'note', id: 'restoring', text: t('backups.restoring'), tone: 'info' })
    for (const entry of m?.backups ?? []) items.push({ kind: 'backup', id: `b-${entry.filename}`, entry, reason: backupReason })
  }

  if (!remote && app.status === 'running') {
    items.push({ kind: 'heading', id: 'h-share', label: t('sections.share') })
    for (const channel of SHARE_CHANNELS) {
      items.push({ kind: 'share', id: `share-${channel}`, channel, link: state.links[channel] ?? null, busy: state.pendingShare === channel, reason: blocked })
      if (state.shareError?.channel === channel) items.push({ kind: 'note', id: `shareError-${channel}`, text: state.shareError.message, tone: 'error' })
    }
  }

  items.push({ kind: 'heading', id: 'h-appearance', label: t('sections.appearance') })
  items.push({ kind: 'theme', id: 'theme', label: t('theme.label'), desc: t('theme.desc'), themeId: appThemeId(app), busy: state.running === 'theme', reason: blocked })

  if (!remote) {
    items.push({ kind: 'heading', id: 'h-package', label: t('sections.package') })
    items.push({ kind: 'action', id: 'export', label: t('export.label'), desc: t('export.desc'), value: t('export.value'), ...working('export'), reason: blocked })
    if (state.exportFile) {
      items.push({ kind: 'copy', id: 'exportFile', label: t('export.file'), value: state.exportFile, desc: t('export.fileDesc'), open: false })
    }
  }

  pushRemove()
  return items
}

// --- the model both halves derive --------------------------------------------

interface PanelModel {
  dispatch: AppDispatch
  app: RegistryApp | undefined
  appKey: string
  items: Item[]
  selectable: SelectableItem[]
  state: PanelState
  connected: boolean
  fresh: boolean
  job: FrameworkLifecycleResult | undefined
}

function usePanelModel(app: RegistryApp | undefined): PanelModel {
  const { t } = useTranslation('appsSettings')
  const dispatch = useAppDispatch()
  const appKey = app ? frameworkAppKey(app.path, app.id) : ''
  const path = app?.path
  const id = app?.id
  const live = useAppSelector(s =>
    path === undefined ? undefined : (s.agentApp.framework.apps.find(a => a.path === path && a.id === id) as RegistryApp | undefined),
  )
  const job = useAppSelector(s => (appKey ? s.agentApp.frameworkLifecycle[appKey] : undefined))
  const connected = useAppSelector(s => s.connection.connected)
  const fresh = useAppSelector(s => s.agentApp.framework.status === 'success')
  const state = usePanelState(appKey)
  const current = live ?? app
  const gone = !!app && !live && fresh
  const items = useMemo(
    () => (current ? buildRows(t, { app: current, job, connected, fresh, gone, state }) : []),
    [t, current, job, connected, fresh, gone, state],
  )
  const selectable = useMemo(() => items.filter(isSelectable), [items])
  return { dispatch, app: current, appKey, items, selectable, state, connected, fresh, job }
}

// --- actions -----------------------------------------------------------------

/** What an action needs: the app, its store key, and the client's dispatch and connection. */
interface Ctx {
  app: RegistryApp
  appKey: string
  dispatch: AppDispatch
  connected: boolean
}

/**
 * Run one host request at a time per app, as the browser does: nothing is
 * sent while disconnected or while another request of this app runs. The
 * outcome (a notice or the error) shows on the status line.
 */
async function act(ctx: Ctx, running: string, fn: () => Promise<string | void>, onError?: (message: string) => void): Promise<void> {
  const { appKey } = ctx
  const entry = metaOf(appKey)
  if (!ctx.connected || entry.pending) return
  entry.pending = true
  entry.version++
  setState(appKey, { running, flash: null })
  try {
    const notice = await fn()
    if (notice) setState(appKey, { flash: { tone: 'success', text: notice } })
  } catch (err) {
    const message = errorText(err)
    if (onError) onError(message)
    else setState(appKey, { flash: { tone: 'error', text: message } })
  } finally {
    entry.pending = false
    setState(appKey, { running: null })
  }
}

function fetchMaintenance(app: RegistryApp): Promise<MaintenanceInfo> {
  return frameworkRequest<MaintenanceInfo>({ operation: 'maintenance', path: app.path, appId: app.id })
}

function savePreference(ctx: Ctx, setting: string, value: boolean | string | number, running: string): void {
  const { app, appKey } = ctx
  void act(ctx, running, async () => {
    const attachment = await frameworkRequest<FrameworkAttachment>({ operation: 'preference', path: app.path, appId: app.id, [setting]: value })
    setState(appKey, { attachment })
  })
}

function saveConsent(ctx: Ctx, allow: boolean, ownerTools: boolean, running: string): void {
  const { app, appKey } = ctx
  void act(ctx, running, async () => {
    const attachment = await frameworkRequest<FrameworkAttachment>({ operation: 'consent', path: app.path, appId: app.id, allow, ownerTools })
    setState(appKey, { attachment })
  })
}

function manage(ctx: Ctx, verb: 'backup' | 'restore' | 'export', backupId?: string): Promise<void> {
  const { app, appKey } = ctx
  return act(ctx, verb, async () => {
    const result = await frameworkRequest<CommandResult>(
      { operation: 'manage', path: app.path, appId: app.id, verb, ...(backupId ? { backupId } : {}) },
      1_250_000,
    )
    if (result.status !== 'success' || result.data?.ok === false) throw new Error(result.stderr?.trim() || tr('common.failed'))
    if (verb === 'export') setState(appKey, { exportFile: result.data?.file ?? null })
    if (verb === 'backup' || verb === 'restore') setState(appKey, { maintenance: await fetchMaintenance(app), maintenanceError: '' })
    return tr(verb === 'backup' ? 'backups.created' : verb === 'restore' ? 'backups.restored' : 'export.done')
  })
}

function deleteBackup(ctx: Ctx, backupId: string): void {
  const { app, appKey } = ctx
  void act(ctx, 'deleteBackup', async () => {
    await frameworkRequest({ operation: 'backup_delete', path: app.path, appId: app.id, backupId })
    setState(appKey, { maintenance: await fetchMaintenance(app), maintenanceError: '' })
    return tr('backups.deleted')
  })
}

function retryMaintenance(ctx: Ctx): void {
  const { app, appKey } = ctx
  void act(
    ctx,
    'retry',
    async () => setState(appKey, { maintenance: await fetchMaintenance(app), maintenanceError: '' }),
    message => setState(appKey, { maintenanceError: message }),
  )
}

function share(ctx: Ctx, action: 'open' | 'close', channel: ShareChannel): void {
  const { app, appKey } = ctx
  if (metaOf(appKey).pending || !ctx.connected) return
  setState(appKey, { pendingShare: channel, shareError: null })
  void act(
    ctx,
    `share:${channel}`,
    async () => {
      const links = await frameworkRequest<Links>({ operation: 'sharing', path: app.path, appId: app.id, action, channel }, 180_000)
      setState(appKey, { links: links ?? {} })
    },
    message => setState(appKey, { shareError: { channel, message } }),
  ).finally(() => setState(appKey, { pendingShare: null }))
}

function chooseTheme(ctx: Ctx, themeId: string): void {
  const { app } = ctx
  void act(ctx, 'theme', async () => {
    await applyTheme(ctx.dispatch, app, themeId)
    const t: Tr = (key, options) => i18next.t(key, options ?? {})
    return t('appsHost:apps.themeSet', { name: app.name, theme: themeName(t, themeId) })
  })
}

function removeFlow(ctx: Ctx, keepFiles: boolean): void {
  const { app, appKey } = ctx
  void act(ctx, 'remove', async () => {
    const outcome = await removeApp(app, keepFiles)
    if (outcome === 'needsKeepFiles') {
      // The host cannot vouch for the folder: offer to forget the entry and keep the files.
      setState(appKey, { confirm: { message: tr('remove.confirmKeepFiles', { name: app.name }), run: () => removeFlow(ctx, true) } })
      return
    }
    const message =
      outcome === 'disconnected'
        ? tr('remove.disconnected', { name: app.name })
        : keepFiles
          ? tr('remove.forgotten', { name: app.name })
          : outcome === 'forgotten'
            ? tr('remove.removedFromList', { name: app.name })
            : tr('remove.deleted', { name: app.name })
    ctx.dispatch(pushToast(message, 'success'))
    requestAppList()
    const onDeleted = onDeletedByKey.get(appKey)
    states.delete(appKey)
    onDeletedByKey.delete(appKey)
    onDeleted?.()
  })
}

function copyText(appKey: string, text: string): void {
  void copyToClipboard(text).then(result =>
    setState(appKey, { flash: result.ok ? { tone: 'success', text: tr('common.copied') } : { tone: 'error', text: tr('common.copyFailed') } }),
  )
}

function openText(appKey: string, target: string): void {
  void openExternal(target).then(ok =>
    setState(appKey, { flash: ok ? { tone: 'info', text: tr('common.opened') } : { tone: 'error', text: tr('common.openFailed') } }),
  )
}

// --- keys --------------------------------------------------------------------

/** The value an open adjuster shows after one step. */
export function adjustStep(adjust: Adjust, delta: -1 | 1): Adjust {
  if (adjust.setting === 'backupInterval') return { setting: 'backupInterval', value: cycleInterval(adjust.value, delta) }
  return { setting: 'backupKeep', value: clampKeep(adjust.value + delta) }
}

function handlePanelKey(model: PanelModel, input: string, key: Key): boolean {
  const { app, appKey, selectable } = model
  if (!app || !appKey) return false
  const ctx: Ctx = { app, appKey, dispatch: model.dispatch, connected: model.connected }
  const state = getState(appKey)
  const entry = metaOf(appKey)

  // Open things take every key until they close.
  if (state.confirm) {
    const pending = state.confirm
    setState(appKey, { confirm: null })
    if (input === 'y' || input === 'Y') pending.run()
    return true
  }
  if (state.picker) {
    const result = themePickerKey(state.picker, input, key, pickerListHeight(entry.pickerRows))
    if (result?.kind === 'move') setState(appKey, { picker: result.state })
    else if (result?.kind === 'cancel') setState(appKey, { picker: null })
    else if (result?.kind === 'apply') {
      setState(appKey, { picker: null })
      if (result.themeId !== appThemeId(app)) chooseTheme(ctx, result.themeId)
    }
    return true
  }
  if (state.adjust) {
    const adjust = state.adjust
    if (key.escape) setState(appKey, { adjust: null })
    else if (key.return || input === ' ') {
      setState(appKey, { adjust: null })
      const saved = adjust.setting === 'backupInterval' ? asInterval(state.attachment?.backupInterval) : clampKeep(state.attachment?.backupKeep || 7)
      if (adjust.value !== saved) savePreference(ctx, adjust.setting, adjust.value, adjust.setting === 'backupInterval' ? 'adjust:interval' : 'adjust:keep')
    } else if (key.leftArrow || key.rightArrow || key.upArrow || key.downArrow || input === '-' || input === '+' || input === 'h' || input === 'l') {
      const delta = key.leftArrow || key.downArrow || input === '-' || input === 'h' ? -1 : 1
      setState(appKey, { adjust: adjustStep(adjust, delta) })
    }
    return true
  }

  if (state.flash) setState(appKey, { flash: null })
  const count = selectable.length
  if (count === 0) return false
  const index = selectedIndex(selectable, state)
  const page = Math.max(1, Math.floor(entry.listHeight / 2))
  let target: number | null = null
  if (key.upArrow || input === 'k') target = index - 1
  else if (key.downArrow || input === 'j') target = index + 1
  else if (key.pageUp) target = index - page
  else if (key.pageDown) target = index + page
  else if (key.home || input === 'g') target = 0
  else if (key.end || input === 'G') target = count - 1
  if (target !== null) {
    const next = Math.max(0, Math.min(count - 1, target))
    setState(appKey, { index: next, selectedId: selectable[next].id })
    return true
  }

  const item = selectable[index]
  const enter = key.return || input === ' '
  const refuse = (reason: string) => {
    setState(appKey, { flash: { tone: 'info', text: reason } })
    return true
  }
  const name = app.name

  switch (item.kind) {
    case 'copy':
      if (input === 'c' || (enter && !item.open)) {
        copyText(appKey, item.value)
        return true
      }
      if (item.open && (input === 'o' || enter)) {
        openText(appKey, item.value)
        return true
      }
      return false
    case 'toggle': {
      if (!enter) return false
      if (item.reason) return refuse(item.reason)
      const running = `toggle:${item.id}`
      if (item.id === 'allow') saveConsent(ctx, !item.value, state.attachment?.ownerToolsAllowed === true, running)
      else if (item.id === 'ownerTools') saveConsent(ctx, true, !item.value, running)
      else savePreference(ctx, item.id, !item.value, running)
      return true
    }
    case 'action':
      if (!enter) return false
      if (item.id === 'requests') {
        setState(appKey, { requestsOpen: !state.requestsOpen })
        return true
      }
      if (item.reason) return refuse(item.reason)
      if (item.id === 'lifecycle') {
        if (!changeAppState(model.dispatch, app, app.status === 'running' ? 'stop' : 'start')) {
          setState(appKey, { flash: { tone: 'error', text: tr('lifecycle.notSent') } })
        }
      } else if (item.id === 'retry') retryMaintenance(ctx)
      else if (item.id === 'backupNow') void manage(ctx, 'backup')
      else if (item.id === 'export') void manage(ctx, 'export')
      else if (item.id === 'remove') {
        const kind = removalKind(app, false)
        const message = tr(kind === 'disconnect' ? 'remove.confirmDisconnect' : kind === 'forget' ? 'remove.confirmForget' : 'remove.confirmDelete', { name })
        setState(appKey, { confirm: { message, run: () => removeFlow(ctx, false) } })
      }
      return true
    case 'interval':
    case 'keep':
      if (!enter) return false
      if (item.reason) return refuse(item.reason)
      setState(appKey, {
        adjust: item.kind === 'interval' ? { setting: 'backupInterval', value: item.value } : { setting: 'backupKeep', value: item.value },
      })
      return true
    case 'theme':
      if (!enter) return false
      if (item.reason) return refuse(item.reason)
      setState(appKey, { picker: openThemePicker(item.themeId) })
      return true
    case 'backup': {
      if (input !== 'r' && input !== 'x' && input !== 'd') return false
      if (item.reason) return refuse(item.reason)
      const { filename, ts } = item.entry
      const date = formatDateTime(new Date(ts))
      if (input === 'r') {
        setState(appKey, {
          confirm: {
            message: tr('backups.confirmRestore', { name, date }),
            run: () => {
              setState(appKey, { restoring: true })
              void manage(ctx, 'restore', filename).finally(() => setState(appKey, { restoring: false }))
            },
          },
        })
      } else {
        setState(appKey, { confirm: { message: tr('backups.confirmDelete', { date }), run: () => deleteBackup(ctx, filename) } })
      }
      return true
    }
    case 'share':
      if (item.link) {
        if (input === 'c' || enter) {
          copyText(appKey, item.link)
          return true
        }
        if (input === 'o') {
          openText(appKey, item.link)
          return true
        }
        if (input === 'x') {
          if (item.reason) return refuse(item.reason)
          const channel = item.channel
          const message = tr(channel === 'lan' ? 'share.confirmCloseLan' : 'share.confirmClosePublic')
          setState(appKey, { confirm: { message, run: () => share(ctx, 'close', channel) } })
          return true
        }
        return false
      }
      if (!enter) return false
      if (item.reason) return refuse(item.reason)
      share(ctx, 'open', item.channel)
      return true
  }
}

/** The panel's key handler: true when it used the key. Esc/Left with nothing open returns false (the caller goes back). */
export function useAppSettingsKeys(app: RegistryApp | undefined, onDeleted?: () => void): (input: string, key: Key) => boolean {
  const model = usePanelModel(app)
  if (model.appKey && onDeleted) onDeletedByKey.set(model.appKey, onDeleted)
  const ref = useRef(model)
  ref.current = model
  const handler = useRef((input: string, key: Key) => handlePanelKey(ref.current, input, key))
  return handler.current
}

// --- rendering ---------------------------------------------------------------

interface Line {
  item: Item
  /** The text of a wrapped note's line. */
  text?: string
}

/** Display lines: long notes wrap to the width, every other row is one line. */
export function layoutLines(items: Item[], columns: number): Line[] {
  const lines: Line[] = []
  for (const item of items) {
    if (item.kind !== 'note') {
      lines.push({ item })
      continue
    }
    const indent = item.bullet ? 4 : 2
    for (const text of wrap(item.text, Math.max(8, columns - indent))) lines.push({ item, text: text.trimEnd() })
  }
  return lines
}

function toneColor(tone: Tone | undefined): string | undefined {
  switch (tone) {
    case 'error':
      return ink.error
    case 'success':
      return ink.success
    case 'warn':
      return ink.warn
    case 'info':
      return ink.info
    case 'muted':
      return ink.muted
    default:
      return undefined
  }
}

function hintLine(t: Tr, item: SelectableItem | undefined, state: PanelState): string {
  const sep = ` ${glyphs().sep} `
  if (state.picker) return [t('hint.apply'), t('hint.move'), t('hint.cancel')].join(sep)
  if (state.confirm) return t('hint.confirm')
  if (state.adjust) return [t('hint.adjust'), t('hint.save'), t('hint.cancel')].join(sep)
  const parts = [t('hint.move')]
  switch (item?.kind) {
    case 'copy':
      parts.push(...(item.open ? [t('hint.open'), t('hint.copy')] : [t('hint.copy')]))
      break
    case 'toggle':
      parts.push(t('hint.switch'))
      break
    case 'action':
      parts.push(t(item.id === 'requests' ? 'hint.showHide' : item.id === 'retry' ? 'hint.retry' : 'hint.run'))
      break
    case 'interval':
    case 'keep':
      parts.push(t('hint.change'))
      break
    case 'theme':
      parts.push(t('hint.choose'))
      break
    case 'backup':
      parts.push(t('hint.restore'), t('hint.delete'))
      break
    case 'share':
      parts.push(...(item.link ? [t('hint.copy'), t('hint.open'), t('hint.closeLink')] : [t('hint.createLink')]))
      break
  }
  return parts.join(sep)
}

function describe(item: SelectableItem | undefined): string {
  if (!item) return ''
  // A row that is itself working keeps its description; others say why they wait.
  if ('reason' in item && item.reason && !('busy' in item && item.busy)) return item.reason
  switch (item.kind) {
    case 'copy':
      return item.value
    case 'backup':
      return item.entry.filename
    case 'share':
      return item.link ?? tr(item.channel === 'lan' ? 'share.lanDesc' : 'share.publicDesc')
    default:
      return item.desc
  }
}

export function AppSettingsPanel({
  app,
  columns,
  rows,
  active,
  onDeleted,
}: {
  app: RegistryApp
  columns: number
  rows: number
  active: boolean
  onDeleted?: () => void
}) {
  const { t } = useTranslation('appsSettings')
  const model = usePanelModel(app)
  const { appKey, items, selectable, state, connected } = model
  const current = model.app ?? app
  if (appKey && onDeleted) onDeletedByKey.set(appKey, onDeleted)
  const g = glyphs()
  const cols = Math.max(24, columns)
  const remote = !!current.connection
  const missing = current.status === 'missing'
  const lifecycleBusy = model.job?.status === 'running'
  const spinning = state.running !== null || lifecycleBusy || state.pendingShare !== null
  const tick = useTicker(100, spinning)
  const frames = spinnerFrames()
  const spinner = spinning ? frames[tick % frames.length] : ''
  const topRef = useRef(0)
  const { path, id: appId, status } = current

  // What the host knows about the app; backups refresh every 30 s while shown.
  useEffect(() => {
    if (!appKey || !connected || missing) return
    let alive = true
    setState(appKey, { loaded: false, loadError: '' })
    frameworkRequest<{ attachments?: FrameworkAttachment[] }>({ operation: 'snapshot' })
      .then(value => {
        if (alive) setState(appKey, { attachment: (value.attachments ?? []).find(a => a.path === path && a.appId === appId), loaded: true })
      })
      .catch(err => {
        if (alive) setState(appKey, { loadError: errorText(err) })
      })
    frameworkRequest<AppDetails>({ operation: 'details', path, appId })
      .then(value => {
        if (alive) setState(appKey, { details: value })
      })
      .catch(err => {
        if (alive) setState(appKey, { loadError: errorText(err) })
      })
    if (remote) {
      return () => {
        alive = false
      }
    }
    const refresh = () =>
      frameworkRequest<MaintenanceInfo>({ operation: 'maintenance', path, appId })
        .then(value => {
          if (alive) setState(appKey, { maintenance: value, maintenanceError: '' })
        })
        .catch(err => {
          if (alive) setState(appKey, { maintenanceError: errorText(err) })
        })
    void refresh()
    const timer = setInterval(() => {
      if (!metaOf(appKey).pending) void refresh()
    }, 30_000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [appKey, connected, missing, remote, path, appId])

  // Share links, again on a status change; a refresh older than an action is dropped.
  useEffect(() => {
    if (!appKey || !connected || missing || remote) return
    let alive = true
    const refresh = () => {
      const version = metaOf(appKey).version
      const stillCurrent = () => alive && version === metaOf(appKey).version && !metaOf(appKey).pending
      return frameworkRequest<Links>({ operation: 'sharing', path, appId, action: 'info' })
        .then(value => {
          if (stillCurrent()) setState(appKey, { links: value ?? {} })
        })
        .catch(err => {
          if (stillCurrent()) setState(appKey, { loadError: errorText(err) })
        })
    }
    void refresh()
    const timer = setInterval(() => {
      if (!metaOf(appKey).pending) void refresh()
    }, 30_000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [appKey, connected, missing, remote, path, appId, status])

  // Leaving the panel closes what was open in it.
  useEffect(
    () => () => {
      if (states.has(appKey)) setState(appKey, { confirm: null, picker: null, adjust: null })
    },
    [appKey],
  )

  const index = selectedIndex(selectable, state)
  const selected = selectable[index]

  // The status block: a confirmation or an outcome (wrapped), else the selected row's description.
  let statusLines: { text: string; color?: string; bold?: boolean }[]
  if (state.confirm) statusLines = wrap(state.confirm.message, cols).slice(0, 4).map(text => ({ text, color: ink.warn, bold: true }))
  else if (state.flash) {
    const color = toneColor(state.flash.tone)
    statusLines = wrap(state.flash.text, cols).slice(0, 3).map(text => ({ text, color }))
  } else {
    const waiting = !!selected && 'reason' in selected && !!selected.reason && !('busy' in selected && selected.busy)
    statusLines = [{ text: truncate(describe(selected), cols), color: waiting ? ink.warn : ink.muted }]
  }

  const listHeight = Math.max(1, rows - 1 - statusLines.length)
  const entry = metaOf(appKey)
  entry.listHeight = listHeight
  entry.pickerRows = Math.max(3, rows - 1)

  const lines = layoutLines(items, cols)
  const selectedLine = selected ? lines.findIndex(line => line.item === selected) : 0
  // Keep the selection in view, with the line above it (often its heading).
  let top = topRef.current
  if (selectedLine - 1 < top) top = Math.max(0, selectedLine - 1)
  if (selectedLine >= top + listHeight) top = selectedLine - listHeight + 1
  top = Math.max(0, Math.min(top, Math.max(0, lines.length - listHeight)))
  topRef.current = top

  // The label column fits the longest label, up to half the width.
  const longest = items.reduce((max, item) => ('label' in item && item.kind !== 'heading' ? Math.max(max, cells(item.label)) : max), 0)
  const labelWidth = Math.min(Math.floor(cols / 2), Math.max(12, longest + 2))
  const valueWidth = Math.max(4, cols - labelWidth - 3)

  const row = (key: string, item: SelectableItem, label: string, value: string, valueColor?: string, labelColor?: string) => {
    const cut = item.kind === 'copy' || (item.kind === 'share' && !!item.link) ? 'middle' : 'end'
    const isSelected = item === selected
    const disabled = 'reason' in item && !!item.reason
    return (
      <Box key={key}>
        <Pointer selected={isSelected} focused={active} />
        <Text {...rowStyle(isSelected, active, labelColor ?? (disabled ? ink.muted : undefined))}>{padEnd(truncate(label, labelWidth - 1), labelWidth)}</Text>
        <Text color={disabled ? ink.muted : valueColor}>{' ' + truncate(value, valueWidth, cut)}</Text>
      </Box>
    )
  }

  const busyValue = (value: string | undefined) => (value ? `${spinner} ${value}`.trim() : '')

  const renderLine = (line: Line, i: number) => {
    const { item } = line
    const key = `${item.id}:${i}`
    switch (item.kind) {
      case 'heading':
        return <Text key={key} bold color={ink.brand}>{truncate(item.label, cols)}</Text>
      case 'note': {
        const first = lines[top + i - 1]?.item !== item
        const lead = item.bullet ? (first ? `  ${g.bullet} ` : '    ') : '  '
        return <Text key={key} color={toneColor(item.tone)}>{lead + truncate(line.text ?? item.text, cols - cells(lead))}</Text>
      }
      case 'info':
        return (
          <Box key={key}>
            <Text>{'  '}</Text>
            <Text color={ink.muted}>{padEnd(truncate(item.label, labelWidth - 1), labelWidth)}</Text>
            <Text color={toneColor(item.tone)}>{' ' + truncate(item.value, valueWidth, 'middle')}</Text>
          </Box>
        )
      case 'copy':
        return row(key, item, item.label, item.value, ink.info)
      case 'toggle': {
        const value = item.busy
          ? busyValue(t('panel.working'))
          : `${item.value ? g.checked : g.unchecked} ${item.value ? t('panel.on') : t('panel.off')}`
        return row(key, item, item.label, value, item.value ? ink.success : ink.muted)
      }
      case 'action': {
        const value = item.busy ? busyValue(item.value) : item.id === 'lifecycle' && lifecycleBusy ? spinner : item.value ?? ''
        return row(key, item, item.label, value, ink.muted, item.danger && !item.reason ? ink.error : undefined)
      }
      case 'interval': {
        const draft = state.adjust?.setting === 'backupInterval' && item === selected ? state.adjust.value : null
        const shown = t(`backups.interval.${draft ?? item.value}`)
        const value = item.busy ? busyValue(t('panel.working')) : draft ? `< ${shown} >` : shown
        return row(key, item, item.label, value)
      }
      case 'keep': {
        const draft = state.adjust?.setting === 'backupKeep' && item === selected ? state.adjust.value : null
        const shown = String(draft ?? item.value)
        const value = item.busy ? busyValue(t('panel.working')) : draft !== null ? `< ${shown} >` : shown
        return row(key, item, item.label, value)
      }
      case 'theme': {
        const value = item.busy
          ? busyValue(t('panel.working'))
          : [themeName(t, item.themeId), themeDescription(t, item.themeId)].filter(Boolean).join(` ${g.sep} `)
        return row(key, item, item.label, value)
      }
      case 'backup': {
        const { ts, size, trigger } = item.entry
        return row(key, item, formatDateTime(new Date(ts)), `${triggerLabel(t, trigger)} ${g.sep} ${formatBytes(size)}`, ink.muted)
      }
      case 'share': {
        const label = t(item.channel === 'lan' ? 'share.lan' : 'share.public')
        if (item.link) return row(key, item, label, item.link, ink.info)
        const pending = state.pendingShare === item.channel
        return row(key, item, label, pending ? busyValue(t('share.starting')) : t(item.channel === 'lan' ? 'share.lanHint' : 'share.publicHint'), ink.muted)
      }
    }
  }

  return (
    <Box flexDirection="column" width={cols}>
      {state.picker ? (
        <ThemePicker
          t={t}
          state={state.picker}
          currentId={appThemeId(current)}
          title={t('appsHost:theme.title', { name: current.name })}
          columns={cols}
          rows={Math.max(3, rows - 1)}
        />
      ) : (
        <>
          <Box flexDirection="column" height={listHeight}>
            {lines.slice(top, top + listHeight).map(renderLine)}
          </Box>
          {statusLines.map((line, i) => (
            <Text key={`status-${i}`} color={line.color} bold={line.bold}>{truncate(line.text, cols)}</Text>
          ))}
        </>
      )}
      <Text color={ink.muted}>{truncate(hintLine(t, selected, state), cols)}</Text>
    </Box>
  )
}
