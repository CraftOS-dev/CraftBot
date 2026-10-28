/**
 * One Agent App's settings, as a keyboard panel: frontend and backend ports,
 * project id and path, theme pack, auto-launch and log cleanup, export as a
 * ZIP, backups (native apps: schedule, keep count, back up now, restore,
 * delete) and sharing links (LAN and public, while running). Every change is
 * the same socket message the browser's Settings > Agent App tab sends.
 *
 * API (AppScreen.tsx and AppsScreen.tsx use exactly this):
 *
 *   <AppSettingsPanel projectId columns rows active />
 *     Renders inside the parent's frame body, at most `rows` lines of
 *     `columns` cells. The last line holds the panel's own key hints. While
 *     `active` and an inner edit is open it sets the screen's text focus.
 *
 *   const panelKey = useAppSettingsKeys(projectId)
 *     A hook: call it during render. It returns the panel's key handler;
 *     call `panelKey(input, key)` first while the panel is shown. It returns
 *     true for keys it used. It never takes Tab, '[', ']', 'q' or Esc, except
 *     while an inner edit is open (a confirmation, the theme picker or the
 *     export path), which takes every key until it closes.
 *
 * Panel keys: j/k or arrows move, Enter or Space acts on the row (switch,
 * choose a theme, save a ZIP, back up now, create a link), Left/Right change
 * a frequency or keep count (Enter saves it), c copies the path or a link,
 * r restores a backup, x deletes a backup or closes a link.
 *
 * The hook and the component render separately, so the state they share
 * (selection, open editors, sharing links) lives in a module store keyed by
 * project id.
 */
import { useEffect, useMemo, useRef, useSyncExternalStore, type ReactNode } from 'react'
import { Box, Text, type Key } from 'ink'
import { useTranslation } from 'react-i18next'
import i18next from 'i18next'
import type { AgentAppProject } from '../../../../browser/frontend/src/types'
import {
  setBackupBusy,
  updateProjectSetting,
  type AgentAppBackupEntry,
  type AgentAppSettingsProject,
} from '../../../../browser/frontend/src/store/slices/agentAppSettingsSlice'
import { RESOURCES, useResource } from '../../../../browser/frontend/src/store/resources'
import { onInboundMessage } from '../../../../browser/frontend/src/store/socket/socketMiddleware'
import { formatDateTime, formatNumber } from '../../../../browser/frontend/src/i18n/format'
import { send, useAppSelector } from '../../state/hooks'
import { store } from '../../state/store'
import { useScreen } from '../context'
import { TextField, fieldKey } from '../../ui/TextField'
import * as TB from '../../input/TextBuffer'
import { glyphs, ink } from '../../theme/theme'
import { padEnd, truncate, width } from '../../text/width'
import {
  appPhase,
  BACKUP_INTERVALS,
  clampKeep,
  cycleValue,
  humanBytes,
  type BackupInterval,
} from './hostModel'
import { copyToClipboard, defaultExportPath, expandPath, exportProject } from './hostUpload'
import {
  applyTheme,
  openThemePicker,
  pickerListHeight,
  projectThemeId,
  themeDescription,
  themeName,
  themePickerKey,
  ThemePicker,
  type ThemePickerState,
} from './hostThemes'

const tr = (key: string, options?: Record<string, unknown>): string => i18next.t(`appsHost:${key}`, options ?? {})

type ShareChannel = 'lan' | 'tunnel'
const SHARE_CHANNELS: ShareChannel[] = ['lan', 'tunnel']
type ToggleSetting = 'autoLaunch' | 'logCleanup' | 'backupsEnabled'

interface Flash {
  tone: 'info' | 'success' | 'error'
  text: string
}

interface PanelConfirm {
  message: string
  run: () => void
}

interface ShareInfo {
  links: Partial<Record<ShareChannel, string | null>>
  error: { channel: ShareChannel; message: string } | null
  pending: ShareChannel | null
}

interface PanelUi {
  /** Index into the selectable rows. */
  index: number
  /** Rows the list had at the last render (PgUp/PgDn step). */
  height: number
  confirm: PanelConfirm | null
  picker: ThemePickerState | null
  exportPath: TB.Buffer | null
  /** The outcome of the last export, shown under the Export row. */
  exportStatus: Flash | null
  /** A one-off message (copied, an error), cleared by the next key. */
  flash: Flash | null
  intervalDraft: BackupInterval | null
  keepDraft: number | null
  /** A restore started here is running. */
  restoring: boolean
  share: ShareInfo
}

const FRESH_UI: PanelUi = {
  index: 0,
  height: 10,
  confirm: null,
  picker: null,
  exportPath: null,
  exportStatus: null,
  flash: null,
  intervalDraft: null,
  keepDraft: null,
  restoring: false,
  share: { links: {}, error: null, pending: null },
}

// ── the shared store ────────────────────────────────────────────────────────

const uis = new Map<string, PanelUi>()
const listeners = new Set<() => void>()

function getUi(projectId: string): PanelUi {
  let ui = uis.get(projectId)
  if (!ui) {
    ui = { ...FRESH_UI }
    uis.set(projectId, ui)
  }
  return ui
}

function setUi(projectId: string, patch: Partial<PanelUi> | ((ui: PanelUi) => Partial<PanelUi>)): void {
  const ui = getUi(projectId)
  uis.set(projectId, { ...ui, ...(typeof patch === 'function' ? patch(ui) : patch) })
  listeners.forEach(l => l())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function usePanelUi(projectId: string): PanelUi {
  return useSyncExternalStore(subscribe, () => getUi(projectId), () => getUi(projectId))
}

// Settings replies carry no project id: remember who asked.
const settingRequests: string[] = []

onInboundMessage(msg => {
  if (msg.type === 'agent_app_sharing_info') {
    const data = (msg.data ?? {}) as { projectId?: string; links?: ShareInfo['links']; error?: ShareInfo['error'] }
    if (!data.projectId || !uis.has(data.projectId)) return
    setUi(data.projectId, { share: { links: data.links ?? {}, error: data.error ?? null, pending: null } })
  } else if (msg.type === 'agent_app_project_setting_update') {
    const projectId = settingRequests.shift()
    if (!projectId) return
    const data = (msg.data ?? {}) as { success?: boolean; error?: string }
    if (!data.success) setUi(projectId, { flash: { tone: 'error', text: data.error || tr('settings.saveFailed') } })
    // The reply carries no project: refetch for the authoritative values.
    send('agent_app_settings_get')
  }
})

// ── the model both halves derive ────────────────────────────────────────────

type Item =
  | { kind: 'info'; id: string; label: string; value: string }
  | { kind: 'path'; id: string; value: string }
  | { kind: 'heading'; id: string; label: string }
  | { kind: 'note'; id: string; text: string; tone: Flash['tone'] | 'muted' }
  | { kind: 'theme'; id: string; themeId: string }
  | { kind: 'toggle'; id: string; setting: ToggleSetting; value: boolean }
  | { kind: 'interval'; id: string; value: BackupInterval }
  | { kind: 'keep'; id: string; value: number }
  | { kind: 'export'; id: string }
  | { kind: 'backupNow'; id: string }
  | { kind: 'backup'; id: string; entry: AgentAppBackupEntry }
  | { kind: 'share'; id: string; channel: ShareChannel; link: string | null }

const SELECTABLE = new Set<Item['kind']>(['path', 'theme', 'toggle', 'interval', 'keep', 'export', 'backupNow', 'backup', 'share'])

interface PanelModel {
  projectId: string
  live: AgentAppProject | undefined
  settings: AgentAppSettingsProject | undefined
  busy: boolean
  ui: PanelUi
  items: Item[]
  selectable: Item[]
}

const fmtWhen = (ms: number): string => formatDateTime(new Date(ms))

function buildItems(
  live: AgentAppProject | undefined,
  settings: AgentAppSettingsProject | undefined,
  loaded: boolean,
  backups: AgentAppBackupEntry[] | undefined,
  busy: boolean,
  restoreResult: { ok: boolean; message: string } | undefined,
  ui: PanelUi,
): Item[] {
  const items: Item[] = []
  if (!live && !settings) {
    items.push({ kind: 'note', id: 'gone', text: loaded ? tr('settings.gone') : tr('settings.loading'), tone: 'muted' })
    return items
  }
  const dash = '-'
  const port = settings?.port ?? live?.port
  items.push({ kind: 'info', id: 'port', label: tr('settings.frontendPort'), value: port != null ? String(port) : dash })
  items.push({ kind: 'info', id: 'backendPort', label: tr('settings.backendPort'), value: settings?.backendPort != null ? String(settings.backendPort) : dash })
  items.push({ kind: 'info', id: 'id', label: tr('settings.projectId'), value: settings?.id ?? live?.id ?? dash })
  const path = settings?.path ?? live?.path
  if (path) items.push({ kind: 'path', id: 'path', value: path })

  items.push({ kind: 'heading', id: 'h-theme', label: tr('settings.appearance') })
  items.push({ kind: 'theme', id: 'theme', themeId: projectThemeId(live) })

  if (!settings) {
    items.push({ kind: 'note', id: 'loading', text: tr('settings.loading'), tone: 'muted' })
    return items
  }

  items.push({ kind: 'heading', id: 'h-prefs', label: tr('settings.preferences') })
  items.push({ kind: 'toggle', id: 'autoLaunch', setting: 'autoLaunch', value: settings.autoLaunch })
  items.push({ kind: 'toggle', id: 'logCleanup', setting: 'logCleanup', value: settings.logCleanup })

  items.push({ kind: 'heading', id: 'h-export', label: tr('settings.export') })
  items.push({ kind: 'export', id: 'export' })
  if (ui.exportStatus) items.push({ kind: 'note', id: 'exportStatus', text: ui.exportStatus.text, tone: ui.exportStatus.tone })

  // Native apps only: external apps have no PocketBase data to back up.
  if (settings.projectType !== 'external') {
    items.push({ kind: 'heading', id: 'h-backups', label: tr('settings.backups') })
    items.push({ kind: 'toggle', id: 'backupsEnabled', setting: 'backupsEnabled', value: settings.backupsEnabled })
    if (settings.backupsEnabled) {
      items.push({ kind: 'interval', id: 'interval', value: settings.backupInterval })
      items.push({ kind: 'keep', id: 'keep', value: settings.backupKeep })
    }
    const status = settings.backupStatus ?? {}
    const statusText = status.lastError
      ? tr('settings.lastBackupFailed', { error: status.lastError })
      : status.lastAt
        ? tr('settings.lastBackup', { when: fmtWhen(status.lastAt * 1000), count: formatNumber(status.count ?? 0), size: humanBytes(status.totalSize ?? 0) })
        : tr('settings.noBackups')
    items.push({ kind: 'note', id: 'backupStatus', text: statusText, tone: status.lastError ? 'error' : 'muted' })
    items.push({ kind: 'backupNow', id: 'backupNow' })
    if (busy && ui.restoring) items.push({ kind: 'note', id: 'restoring', text: tr('settings.restoring'), tone: 'info' })
    else if (restoreResult) {
      items.push({ kind: 'note', id: 'restoreResult', text: restoreResult.ok ? tr('settings.restored') : restoreResult.message, tone: restoreResult.ok ? 'success' : 'error' })
    }
    if (backups === undefined) items.push({ kind: 'note', id: 'backupsLoading', text: tr('settings.loading'), tone: 'muted' })
    for (const entry of backups ?? []) items.push({ kind: 'backup', id: `b-${entry.filename}`, entry })
  }

  // Sharing needs a running app.
  if (appPhase(live?.status ?? settings.status) === 'running') {
    items.push({ kind: 'heading', id: 'h-share', label: tr('settings.share') })
    for (const channel of SHARE_CHANNELS) items.push({ kind: 'share', id: `share-${channel}`, channel, link: ui.share.links[channel] ?? null })
    if (ui.share.error) items.push({ kind: 'note', id: 'shareError', text: ui.share.error.message, tone: 'error' })
  }
  return items
}

function usePanelModel(projectId: string): PanelModel {
  const live = useAppSelector(s => s.agentApp.projects.find(p => p.id === projectId))
  const settings = useAppSelector(s => s.agentAppSettings.projects.find(p => p.id === projectId))
  const loaded = useAppSelector(s => s.agentAppSettings.hasLoadedProjects)
  const backups = useAppSelector(s => s.agentAppSettings.backupsByProject[projectId])
  const busy = useAppSelector(s => !!s.agentAppSettings.backupBusy[projectId])
  const restoreResult = useAppSelector(s => s.agentAppSettings.backupRestoreResult[projectId])
  const ui = usePanelUi(projectId)
  const items = useMemo(
    () => buildItems(live, settings, loaded, backups, busy, restoreResult, ui),
    [live, settings, loaded, backups, busy, restoreResult, ui],
  )
  const selectable = useMemo(() => items.filter(item => SELECTABLE.has(item.kind)), [items])
  return { projectId, live, settings, busy, ui, items, selectable }
}

// ── keys ────────────────────────────────────────────────────────────────────

function saveSetting(projectId: string, setting: ToggleSetting | 'backupInterval' | 'backupKeep', value: boolean | string | number): void {
  store.dispatch(updateProjectSetting({ projectId, setting, value }))
  settingRequests.push(projectId)
  send('agent_app_project_setting_update', { projectId, setting, value })
}

function startExport(model: PanelModel, target: string): void {
  const { projectId } = model
  const path = expandPath(target)
  if (!path) return
  setUi(projectId, { exportPath: null, exportStatus: { tone: 'info', text: tr('settings.exporting') } })
  exportProject(projectId, path).then(
    size => setUi(projectId, { exportStatus: { tone: 'success', text: tr('settings.exported', { path, size: humanBytes(size) }) } }),
    err => setUi(projectId, { exportStatus: { tone: 'error', text: tr('settings.exportFailed', { message: err instanceof Error ? err.message : String(err) }) } }),
  )
}

function handlePanelKey(model: PanelModel, input: string, key: Key): boolean {
  const { projectId, selectable } = model
  if (!projectId) return false
  const ui = getUi(projectId)
  const name = model.live?.name ?? model.settings?.name ?? projectId

  // Inner edits take every key until they close.
  if (ui.confirm) {
    const pending = ui.confirm
    setUi(projectId, { confirm: null })
    if (input === 'y' || input === 'Y') pending.run()
    return true
  }
  if (ui.picker) {
    const result = themePickerKey(ui.picker, input, key, pickerListHeight(ui.height + 1))
    if (result?.kind === 'move') setUi(projectId, { picker: result.state })
    else if (result?.kind === 'cancel') setUi(projectId, { picker: null })
    else if (result?.kind === 'apply') {
      setUi(projectId, { picker: null })
      if (model.live) applyTheme(store.dispatch, model.live, result.themeId)
      else send('agent_app_theme_update', { projectId, theme: { themeId: result.themeId } })
    }
    return true
  }
  if (ui.exportPath) {
    if (key.escape) setUi(projectId, { exportPath: null })
    else if (key.return) startExport(model, ui.exportPath.text)
    else {
      const next = fieldKey(ui.exportPath, input, key)
      if (next) setUi(projectId, { exportPath: next })
    }
    return true
  }

  if (ui.flash) setUi(projectId, { flash: null })
  const count = selectable.length
  if (count === 0) return false
  const index = Math.min(ui.index, count - 1)
  const move = (to: number) => {
    const next = Math.max(0, Math.min(count - 1, to))
    setUi(projectId, { index: next, intervalDraft: null, keepDraft: null })
  }
  const page = Math.max(1, Math.floor(ui.height / 2))
  let target: number | null = null
  if (key.upArrow || input === 'k') target = index - 1
  else if (key.downArrow || input === 'j') target = index + 1
  else if (key.pageUp) target = index - page
  else if (key.pageDown) target = index + page
  else if (key.home || input === 'g') target = 0
  else if (key.end || input === 'G') target = count - 1
  if (target !== null) {
    move(target)
    return true
  }

  const item = selectable[index]
  const activate = key.return || input === ' '
  switch (item.kind) {
    case 'path':
      if (input === 'c') {
        copyToClipboard(item.value)
        setUi(projectId, { flash: { tone: 'success', text: tr('settings.copied') } })
        return true
      }
      return false
    case 'theme':
      if (activate || key.rightArrow) {
        setUi(projectId, { picker: openThemePicker(item.themeId) })
        return true
      }
      return false
    case 'toggle':
      if (activate) {
        saveSetting(projectId, item.setting, !item.value)
        return true
      }
      return false
    case 'interval':
      if (key.leftArrow || key.rightArrow) {
        setUi(projectId, { intervalDraft: cycleValue(BACKUP_INTERVALS, ui.intervalDraft ?? item.value, key.leftArrow ? -1 : 1) })
        return true
      }
      if (key.return) {
        if (ui.intervalDraft && ui.intervalDraft !== item.value) saveSetting(projectId, 'backupInterval', ui.intervalDraft)
        setUi(projectId, { intervalDraft: null })
        return true
      }
      return false
    case 'keep':
      if (key.leftArrow || key.rightArrow || input === '-' || input === '+') {
        const delta = key.leftArrow || input === '-' ? -1 : 1
        setUi(projectId, { keepDraft: clampKeep((ui.keepDraft ?? item.value) + delta) })
        return true
      }
      if (key.return) {
        // Saved only on Enter: lowering the count prunes old archives at once.
        if (ui.keepDraft !== null && ui.keepDraft !== item.value) saveSetting(projectId, 'backupKeep', ui.keepDraft)
        setUi(projectId, { keepDraft: null })
        return true
      }
      return false
    case 'export':
      if (activate) {
        const file = `${name.replace(/[<>:"/\\|?*\s]+/g, '_') || projectId}.zip`
        setUi(projectId, { exportPath: TB.fromText(defaultExportPath(file)), exportStatus: null })
        return true
      }
      return false
    case 'backupNow':
      if (activate) {
        if (model.busy) setUi(projectId, { flash: { tone: 'info', text: tr('settings.backupBusy') } })
        else {
          store.dispatch(setBackupBusy({ projectId, busy: true }))
          send('agent_app_backup_now', { projectId })
          setUi(projectId, { flash: { tone: 'info', text: tr('settings.backingUp') } })
        }
        return true
      }
      return false
    case 'backup': {
      const { filename, ts } = item.entry
      if (input === 'r') {
        if (model.busy) {
          setUi(projectId, { flash: { tone: 'info', text: tr('settings.backupBusy') } })
          return true
        }
        setUi(projectId, {
          confirm: {
            message: tr('settings.confirmRestore', { name, date: fmtWhen(ts) }),
            run: () => {
              setUi(projectId, { restoring: true })
              store.dispatch(setBackupBusy({ projectId, busy: true }))
              send('agent_app_backup_restore', { projectId, filename })
            },
          },
        })
        return true
      }
      if (input === 'x') {
        setUi(projectId, {
          confirm: {
            message: tr('settings.confirmDeleteBackup', { date: fmtWhen(ts) }),
            run: () => send('agent_app_backup_delete', { projectId, filename }),
          },
        })
        return true
      }
      return false
    }
    case 'share':
      if (item.link && (input === 'c' || activate)) {
        copyToClipboard(item.link)
        setUi(projectId, { flash: { tone: 'success', text: tr('settings.copied') } })
        return true
      }
      if (!item.link && activate) {
        if (ui.share.pending) return true
        setUi(projectId, s => ({ share: { ...s.share, pending: item.channel, error: null } }))
        send('agent_app_share_open', { projectId, channel: item.channel })
        return true
      }
      if (item.link && input === 'x') {
        setUi(projectId, {
          confirm: {
            message: tr(item.channel === 'lan' ? 'settings.confirmCloseLan' : 'settings.confirmClosePublic'),
            run: () => send('agent_app_share_close', { projectId, channel: item.channel }),
          },
        })
        return true
      }
      return false
    default:
      return false
  }
}

/** The panel's key handler for the parent to call first (see the API above). */
export function useAppSettingsKeys(projectId: string): (input: string, key: Key) => boolean {
  const model = usePanelModel(projectId)
  const ref = useRef(model)
  ref.current = model
  const handler = useRef((input: string, key: Key) => handlePanelKey(ref.current, input, key))
  return handler.current
}

// ── rendering ───────────────────────────────────────────────────────────────

function hintsFor(item: Item | undefined, ui: PanelUi, t: (k: string) => string): string {
  if (ui.picker) return t('settings.hints.picker')
  if (ui.exportPath) return t('settings.hints.exportPath')
  const move = t('settings.hints.move')
  if (!item) return move
  const specific: Partial<Record<Item['kind'], string>> = {
    path: t('settings.hints.copy'),
    theme: t('settings.hints.choose'),
    toggle: t('settings.hints.toggle'),
    interval: t('settings.hints.adjust'),
    keep: t('settings.hints.adjust'),
    export: t('settings.hints.export'),
    backupNow: t('settings.hints.backupNow'),
    backup: t('settings.hints.backup'),
  }
  const extra = item.kind === 'share' ? t(item.link ? 'settings.hints.shareOpen' : 'settings.hints.shareCreate') : specific[item.kind]
  return extra ? `${move} · ${extra}` : move
}

export function AppSettingsPanel({ projectId, columns, rows, active }: { projectId: string; columns: number; rows: number; active: boolean }) {
  const { t } = useTranslation('appsHost')
  const { setTextFocus } = useScreen()
  useResource(RESOURCES.agentAppSettings)
  const model = usePanelModel(projectId)
  const { live, settings, ui, items, selectable } = model
  const g = glyphs()
  const cols = Math.max(24, columns)
  const listHeight = Math.max(1, rows - 2)
  const topRef = useRef(0)

  // The handler pages by the list's height.
  getUi(projectId).height = listHeight

  const native = !!settings && settings.projectType !== 'external'
  const running = appPhase(live?.status ?? settings?.status) === 'running'
  const backupsMissing = useAppSelector(s => s.agentAppSettings.backupsByProject[projectId] === undefined)
  useEffect(() => {
    if (native && backupsMissing) send('agent_app_backups_list', { projectId })
  }, [projectId, native, backupsMissing])
  useEffect(() => {
    if (running) send('agent_app_sharing_info', { projectId })
  }, [projectId, running])
  useEffect(() => {
    if (!model.busy && ui.restoring) setUi(projectId, { restoring: false })
  }, [model.busy, ui.restoring, projectId])

  const editing = !!ui.exportPath || !!ui.picker || !!ui.confirm
  const focusSet = useRef(false)
  useEffect(() => {
    if (!active) return
    if (editing) {
      setTextFocus(true)
      focusSet.current = true
    } else if (focusSet.current) {
      setTextFocus(false)
      focusSet.current = false
    }
  }, [active, editing, setTextFocus])
  useEffect(
    () => () => {
      if (focusSet.current) setTextFocus(false)
    },
    [setTextFocus],
  )

  const index = Math.min(ui.index, Math.max(0, selectable.length - 1))
  const selected = selectable[index]
  const selectedLine = selected ? items.indexOf(selected) : 0
  // Keep the selection in view, with the row above it (often its heading).
  let top = topRef.current
  if (selectedLine - 1 < top) top = Math.max(0, selectedLine - 1)
  if (selectedLine >= top + listHeight) top = selectedLine - listHeight + 1
  top = Math.max(0, Math.min(top, Math.max(0, items.length - listHeight)))
  topRef.current = top

  const labelWidth = Math.min(26, Math.max(12, Math.floor(cols * 0.36)))
  const valueWidth = Math.max(4, cols - labelWidth - 2)
  const toneColor = (tone: Flash['tone'] | 'muted') =>
    tone === 'error' ? ink.error : tone === 'success' ? ink.success : tone === 'info' ? ink.info : ink.muted

  const row = (item: Item, isSelected: boolean, label: string, value: string, valueColor?: string) => (
    <Box key={item.id}>
      <Text color={isSelected ? ink.focus : undefined}>{isSelected && active ? `${g.pointer} ` : '  '}</Text>
      <Text bold={isSelected} color={isSelected ? ink.focus : undefined}>{padEnd(label, labelWidth)}</Text>
      <Text color={valueColor}>{truncate(value, valueWidth, 'middle')}</Text>
    </Box>
  )

  const renderItem = (item: Item) => {
    const isSelected = item === selected
    switch (item.kind) {
      case 'heading':
        return <Text key={item.id} bold color={ink.brand}>{truncate(item.label, cols)}</Text>
      case 'note':
        return <Text key={item.id} color={toneColor(item.tone)}>{'  ' + truncate(item.text, cols - 2)}</Text>
      case 'info':
        return row(item, false, item.label, item.value)
      case 'path':
        return row(item, isSelected, t('settings.path'), item.value)
      case 'theme':
        return row(item, isSelected, t('settings.themePack'), `${themeName(t, item.themeId)} · ${themeDescription(t, item.themeId)}`)
      case 'toggle': {
        const label = t(`settings.${item.setting}`)
        const value = `${item.value ? g.checked : g.unchecked} ${item.value ? t('settings.on') : t('settings.off')}`
        return row(item, isSelected, label, value, item.value ? ink.success : ink.muted)
      }
      case 'interval': {
        const draft = ui.intervalDraft && isSelected ? ui.intervalDraft : null
        const value = t(`settings.interval.${draft ?? item.value}`)
        return row(item, isSelected, t('settings.frequency'), isSelected ? `< ${value} >${draft && draft !== item.value ? '  ' + t('settings.enterSaves') : ''}` : value)
      }
      case 'keep': {
        const draft = ui.keepDraft !== null && isSelected ? ui.keepDraft : null
        const value = String(draft ?? item.value)
        return row(item, isSelected, t('settings.keep'), isSelected ? `< ${value} >${draft !== null && draft !== item.value ? '  ' + t('settings.enterSaves') : ''}` : value)
      }
      case 'export':
        return row(item, isSelected, t('settings.exportZip'), t('settings.exportValue'), ink.muted)
      case 'backupNow':
        return row(item, isSelected, t('settings.backupNow'), model.busy ? t('settings.working') : '', ink.muted)
      case 'backup': {
        const { ts, trigger, size } = item.entry
        const triggerLabel = t(`settings.trigger.${trigger}`, { defaultValue: trigger })
        return row(item, isSelected, fmtWhen(ts), `${triggerLabel} · ${humanBytes(size)}`, ink.muted)
      }
      case 'share': {
        const label = t(item.channel === 'lan' ? 'settings.lan' : 'settings.public')
        if (item.link) return row(item, isSelected, label, item.link, ink.info)
        const pending = ui.share.pending === item.channel
        return row(item, isSelected, label, pending ? t('settings.starting') : t(item.channel === 'lan' ? 'settings.lanHint' : 'settings.publicHint'), ink.muted)
      }
    }
  }

  const describe = (item: Item | undefined): string => {
    if (!item) return ''
    switch (item.kind) {
      case 'path':
        return item.value
      case 'theme':
        return t('settings.themeDesc')
      case 'toggle':
        return t(`settings.${item.setting}Desc`)
      case 'interval':
        return t('settings.frequencyDesc')
      case 'keep':
        return t('settings.keepDesc')
      case 'export':
        return t('settings.exportDesc')
      case 'backupNow':
        return t('settings.backupNowDesc')
      case 'backup':
        return item.entry.filename
      case 'share':
        return item.link ?? t(item.channel === 'lan' ? 'settings.lanDesc' : 'settings.publicDesc')
      default:
        return ''
    }
  }

  let statusLine: ReactNode
  if (ui.exportPath) {
    statusLine = <TextField label={t('settings.saveTo')} buffer={ui.exportPath} focused={active} width={cols} />
  } else if (ui.confirm) {
    const hint = t('settings.confirmHint')
    statusLine = (
      <Box>
        <Text color={ink.warn} bold>{truncate(ui.confirm.message, Math.max(10, cols - width(hint) - 2))}</Text>
        <Text color={ink.muted}>{'  ' + hint}</Text>
      </Box>
    )
  } else if (ui.flash) {
    statusLine = <Text color={toneColor(ui.flash.tone)}>{truncate(ui.flash.text, cols)}</Text>
  } else {
    statusLine = <Text color={ink.muted}>{truncate(describe(selected), cols)}</Text>
  }

  return (
    <Box flexDirection="column" width={cols}>
      {ui.picker ? (
        <ThemePicker
          t={t}
          state={ui.picker}
          currentId={projectThemeId(live)}
          title={t('theme.title', { name: live?.name ?? settings?.name ?? projectId })}
          columns={cols}
          rows={listHeight + 1}
        />
      ) : (
        <Box flexDirection="column" height={listHeight}>
          {items.slice(top, top + listHeight).map(renderItem)}
        </Box>
      )}
      {ui.picker ? null : statusLine}
      <Text color={ink.muted}>{truncate(hintsFor(selected, ui, t), cols)}</Text>
    </Box>
  )
}
