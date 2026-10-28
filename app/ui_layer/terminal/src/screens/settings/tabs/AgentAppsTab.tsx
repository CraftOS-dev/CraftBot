/**
 * Settings > Agent Apps: every Agent App project with its status. Enter
 * opens one: launch or stop, its ports, id and path, auto launch and log
 * cleanup, scheduled backups (frequency, how many to keep, back up now,
 * restore and delete archives, both confirmed), LAN and public share links
 * (create, copy, open, close), export as a ZIP to a path, and delete
 * (confirm). Leftover backups of deleted apps can be restored into another
 * app or deleted. Same messages as the browser's tab.
 */
import { useEffect, useState } from 'react'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../../../state/hooks'
import {
  setBackupBusy,
  updateProjectSetting,
  type AgentAppBackupEntry,
  type AgentAppBackupOrphan,
  type AgentAppSettingsProject,
} from '../../../../../browser/frontend/src/store/slices/agentAppSettingsSlice'
import {
  selectAgentAppSettingsHasLoadedProjects,
  selectAgentAppSettingsProjects,
} from '../../../../../browser/frontend/src/store/selectors/agentAppSettings'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { getApiBaseUrl } from '../../../platform/connection'
import { useTab } from '../tabContext'
import { clampList, listKey, LIST_START } from '../../../ui/list'
import { confirmKey, type PendingConfirm } from '../../../ui/Confirm'
import { TextField, fieldKey } from '../../../ui/TextField'
import * as TB from '../../../input/TextBuffer'
import { glyphs, ink } from '../../../theme/theme'
import { padEnd, truncate, width as cells } from '../../../text/width'
import { copyToClipboard } from '../connectClipboard'
import { openExternal } from '../connectOpen'
import {
  formatBytes,
  NoticeLine,
  Row,
  str,
  useConnectKeys,
  useHints,
  useInbound,
  useNotice,
  useSpinner,
  useTextFocus,
  ConfirmBlock,
} from '../connectKit'

type ShareChannel = 'lan' | 'tunnel'
type Setting = 'autoLaunch' | 'logCleanup' | 'backupsEnabled' | 'backupInterval' | 'backupKeep'
const INTERVALS = ['hourly', '6h', 'daily', 'weekly'] as const
const CHANNELS: ShareChannel[] = ['lan', 'tunnel']

type DetailRow =
  | { kind: 'heading'; label: string }
  | { kind: 'text'; label: string; color?: string }
  | { kind: 'info'; label: string; value: string; copy?: string }
  | { kind: 'toggle'; label: string; setting: Setting; value: boolean }
  | { kind: 'interval'; label: string; value: string }
  | { kind: 'keep'; label: string; value: number }
  | { kind: 'action'; id: 'launch' | 'stop' | 'backup' | 'export' | 'delete'; label: string; danger?: boolean }
  | { kind: 'backup'; entry: AgentAppBackupEntry }
  | { kind: 'share'; channel: ShareChannel; link: string | null }

type View =
  | { kind: 'list' }
  | { kind: 'project'; id: string; index: number; top: number }
  | { kind: 'orphan'; id: string; index: number; target: string | null }
  | { kind: 'export'; id: string; path: TB.Buffer; busy: boolean; error: string }

const selectable = (row: DetailRow) => row.kind !== 'heading' && row.kind !== 'text'

function isActive(status: string): boolean {
  return status === 'running' || status === 'creating' || status === 'launching'
}

function defaultExportPath(name: string): string {
  const downloads = join(homedir(), 'Downloads')
  const file = `${name.replace(/[\\/:*?"<>|\s]+/g, '_') || 'agent-app'}.zip`
  return join(existsSync(downloads) ? downloads : homedir(), file)
}

export function AgentAppsTab() {
  const { t, i18n } = useTranslation('settingsConnect')
  const dispatch = useAppDispatch()
  const { active, width, height } = useTab()
  useResource(RESOURCES.agentAppSettings)
  const projects = useAppSelector(selectAgentAppSettingsProjects)
  const hasLoaded = useAppSelector(selectAgentAppSettingsHasLoadedProjects)
  const orphans = useAppSelector(s => s.agentAppSettings.backupOrphans)
  const backupsByProject = useAppSelector(s => s.agentAppSettings.backupsByProject)
  const backupBusy = useAppSelector(s => s.agentAppSettings.backupBusy)
  const restoreResult = useAppSelector(s => s.agentAppSettings.backupRestoreResult)

  const [view, setView] = useState<View>({ kind: 'list' })
  const [list, setList] = useState(LIST_START)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [inProgress, setInProgress] = useState<string | null>(null)
  const [restoring, setRestoring] = useState<string | null>(null)
  const [shares, setShares] = useState<Record<string, { links: Partial<Record<ShareChannel, string | null>>; error: { channel: ShareChannel; message: string } | null; pending: ShareChannel | null }>>({})
  const [notice, showNotice] = useNotice()

  const listHeight = Math.max(3, height - 5)
  const listView = clampList(list, projects.length + orphans.length, listHeight)
  const project = view.kind === 'project' || view.kind === 'export' ? projects.find(p => p.id === view.id) ?? null : null
  const orphan = view.kind === 'orphan' ? orphans.find(o => o.id === view.id) ?? null : null
  const targets = projects.filter(p => (p.projectType || 'native') !== 'external')

  useTextFocus(active && view.kind === 'export' && !view.busy)
  const spinner = useSpinner(inProgress !== null || Object.values(backupBusy).some(Boolean) || (view.kind === 'export' && view.busy))

  // Archive lists and share links load when their view opens.
  const viewProjectId = view.kind === 'project' ? view.id : view.kind === 'orphan' ? view.id : null
  const running = project?.status === 'running'
  useEffect(() => {
    if (!viewProjectId) return
    if (backupsByProject[viewProjectId] === undefined) send('agent_app_backups_list', { projectId: viewProjectId })
  }, [viewProjectId])
  useEffect(() => {
    if (view.kind === 'project' && running) send('agent_app_sharing_info', { projectId: view.id })
  }, [view.kind === 'project' ? view.id : null, running])
  useEffect(() => {
    if (restoring && !backupBusy[restoring]) setRestoring(null)
  }, [backupBusy, restoring])

  useInbound(
    ['agent_app_launch', 'agent_app_stop', 'agent_app_delete', 'agent_app_project_setting_update', 'agent_app_sharing_info', 'agent_app_backup_delete', 'agent_app_backup_now_result'],
    (type, d) => {
      if (type === 'agent_app_launch' || type === 'agent_app_stop' || type === 'agent_app_delete') {
        setInProgress(null)
        if (d.success === false) showNotice(str(d.error) || t('apps.actionFailed'), 'error')
      } else if (type === 'agent_app_project_setting_update') {
        if (d.success === false) {
          showNotice(str(d.error) || t('apps.settingFailed'), 'error')
          send('agent_app_settings_get')
        }
      } else if (type === 'agent_app_sharing_info') {
        const projectId = str(d.projectId)
        if (!projectId) return
        setShares(prev => ({
          ...prev,
          [projectId]: {
            links: (d.links as Partial<Record<ShareChannel, string | null>>) ?? {},
            error: (d.error as { channel: ShareChannel; message: string } | null) ?? null,
            pending: null,
          },
        }))
      } else if (type === 'agent_app_backup_delete') {
        if (d.success === false) showNotice(str(d.error) || t('apps.backupDeleteFailed'), 'error')
      } else if (type === 'agent_app_backup_now_result') {
        if (str(d.projectId) && str(d.status) && str(d.status) !== 'success') {
          const errors = Array.isArray(d.errors) ? (d.errors as unknown[]).map(String) : []
          showNotice(errors[0] || t('apps.backupFailed'), 'error')
        }
      }
    },
  )

  const when = (ms: number) => new Date(ms).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'short' })
  const statusText = (status: string) =>
    status === 'running'
      ? t('apps.status.running')
      : status === 'creating'
        ? t('apps.status.creating')
        : status === 'launching'
          ? t('apps.status.launching')
          : status === 'error'
            ? t('apps.status.error')
            : t('apps.status.notRunning')
  const statusMark = (status: string): [string, string | undefined] => {
    const g = glyphs()
    if (status === 'running') return [g.unread, ink.success]
    if (status === 'creating' || status === 'launching') return [g.running, ink.warn]
    if (status === 'error') return [g.failed, ink.error]
    return [g.idle, ink.muted]
  }
  const triggerText = (trigger: string) => (['scheduled', 'pre_promote', 'manual', 'pre_delete', 'pre_restore'].includes(trigger) ? t(`apps.trigger.${trigger}`) : trigger)
  const backupLabel = (entry: AgentAppBackupEntry) => `${when(entry.ts)} · ${triggerText(entry.trigger)} · ${formatBytes(entry.size)}`

  // ── Project detail rows ──
  const detailRows = (p: AgentAppSettingsProject): DetailRow[] => {
    const rows: DetailRow[] = []
    const canLaunch = ['created', 'stopped', 'ready', 'error'].includes(p.status)
    rows.push({ kind: 'heading', label: t('apps.runtime') })
    if (p.status === 'running') rows.push({ kind: 'action', id: 'stop', label: t('apps.stop') })
    else if (canLaunch) rows.push({ kind: 'action', id: 'launch', label: t('apps.launch') })
    rows.push({ kind: 'info', label: t('apps.frontendPort'), value: p.port != null ? String(p.port) : '-' })
    rows.push({ kind: 'info', label: t('apps.backendPort'), value: p.backendPort != null ? String(p.backendPort) : '-' })
    rows.push({ kind: 'info', label: t('apps.projectId'), value: p.id, copy: p.id })
    rows.push({ kind: 'info', label: t('apps.path'), value: p.path, copy: p.path })
    rows.push({ kind: 'heading', label: t('apps.preferences') })
    rows.push({ kind: 'toggle', label: t('apps.autoLaunch'), setting: 'autoLaunch', value: p.autoLaunch })
    rows.push({ kind: 'toggle', label: t('apps.logCleanup'), setting: 'logCleanup', value: p.logCleanup })
    if (p.projectType !== 'external') {
      rows.push({ kind: 'heading', label: t('apps.backups') })
      rows.push({ kind: 'toggle', label: t('apps.scheduledBackups'), setting: 'backupsEnabled', value: p.backupsEnabled })
      if (p.backupsEnabled) {
        rows.push({ kind: 'interval', label: t('apps.frequency'), value: p.backupInterval })
        rows.push({ kind: 'keep', label: t('apps.keep'), value: p.backupKeep })
      }
      const status = p.backupStatus ?? {}
      rows.push({
        kind: 'text',
        label: status.lastError
          ? t('apps.lastBackupFailed', { error: status.lastError })
          : status.lastAt
            ? t('apps.lastBackup', { when: when(status.lastAt * 1000), count: status.count ?? 0, size: formatBytes(status.totalSize ?? 0) })
            : t('apps.noBackupsYet'),
        color: status.lastError ? ink.error : ink.muted,
      })
      rows.push({ kind: 'action', id: 'backup', label: backupBusy[p.id] && restoring !== p.id ? `${spinner} ${t('apps.backingUp')}` : t('apps.backupNow') })
      if (restoring === p.id && backupBusy[p.id]) rows.push({ kind: 'text', label: `${spinner} ${t('apps.restoringInto', { name: p.name })}`, color: ink.muted })
      const result = restoreResult[p.id]
      if (result && !backupBusy[p.id]) rows.push({ kind: 'text', label: result.message, color: result.ok ? ink.success : ink.error })
      const archives = backupsByProject[p.id]
      if (archives === undefined) rows.push({ kind: 'text', label: t('common.loading'), color: ink.muted })
      else for (const entry of archives) rows.push({ kind: 'backup', entry })
    }
    if (p.status === 'running') {
      rows.push({ kind: 'heading', label: t('apps.share') })
      const share = shares[p.id]
      for (const channel of CHANNELS) {
        rows.push({ kind: 'share', channel, link: share?.links[channel] ?? null })
        if (share?.error?.channel === channel) rows.push({ kind: 'text', label: share.error.message, color: ink.error })
      }
    }
    rows.push({ kind: 'heading', label: t('apps.project') })
    rows.push({ kind: 'action', id: 'export', label: t('apps.export') })
    rows.push({ kind: 'action', id: 'delete', label: t('apps.delete'), danger: true })
    return rows
  }

  const rows = project && view.kind === 'project' ? detailRows(project) : []
  const detailHeight = Math.max(3, height - 2)
  const firstSelectable = rows.findIndex(selectable)
  const rowIndex = view.kind === 'project' ? (rows[view.index] && selectable(rows[view.index]) ? view.index : Math.max(0, firstSelectable)) : 0

  const changeSetting = (p: AgentAppSettingsProject, setting: Setting, value: boolean | string | number) => {
    dispatch(updateProjectSetting({ projectId: p.id, setting, value }))
    send('agent_app_project_setting_update', { projectId: p.id, setting, value })
  }

  const copy = (text: string, label: string) => {
    void copyToClipboard(text).then(r => showNotice(r.ok ? t('apps.copied', { what: label }) : t('apps.copyFailed'), r.ok ? 'success' : 'error'))
  }

  const openShare = (p: AgentAppSettingsProject, channel: ShareChannel) => {
    setShares(prev => ({ ...prev, [p.id]: { links: prev[p.id]?.links ?? {}, error: null, pending: channel } }))
    send('agent_app_share_open', { projectId: p.id, channel })
  }

  const restore = (p: AgentAppSettingsProject, entry: AgentAppBackupEntry) => {
    setConfirm({
      message: t('apps.confirmRestore', { name: p.name, date: when(entry.ts) }),
      onConfirm: () => {
        setRestoring(p.id)
        dispatch(setBackupBusy({ projectId: p.id, busy: true }))
        send('agent_app_backup_restore', { projectId: p.id, filename: entry.filename })
      },
    })
  }

  const runAction = (p: AgentAppSettingsProject, id: 'launch' | 'stop' | 'backup' | 'export' | 'delete') => {
    if (id === 'launch' || id === 'stop') {
      setInProgress(p.id)
      send(id === 'launch' ? 'agent_app_launch' : 'agent_app_stop', { projectId: p.id })
      showNotice(id === 'launch' ? t('apps.launching', { name: p.name }) : t('apps.stopping', { name: p.name }))
    } else if (id === 'backup') {
      if (backupBusy[p.id]) return
      dispatch(setBackupBusy({ projectId: p.id, busy: true }))
      send('agent_app_backup_now', { projectId: p.id })
    } else if (id === 'export') {
      setView({ kind: 'export', id: p.id, path: TB.fromText(defaultExportPath(p.name)), busy: false, error: '' })
    } else {
      setConfirm({
        message: t('apps.confirmDelete', { name: p.name }),
        onConfirm: () => {
          setInProgress(p.id)
          send('agent_app_delete', { projectId: p.id })
          setView({ kind: 'list' })
        },
      })
    }
  }

  const exportZip = async (p: AgentAppSettingsProject, target: string) => {
    if (view.kind !== 'export') return
    const path = resolve(target)
    setView({ ...view, busy: true, error: '' })
    try {
      const resp = await fetch(`${getApiBaseUrl()}/api/agent-app/${encodeURIComponent(p.id)}/export`)
      if (!resp.ok) throw new Error(t('apps.exportHttp', { status: resp.status }))
      const bytes = Buffer.from(await resp.arrayBuffer())
      mkdirSync(dirname(path), { recursive: true })
      writeFileSync(path, bytes)
      setView({ kind: 'project', id: p.id, index: 0, top: 0 })
      showNotice(t('apps.exported', { path, size: formatBytes(bytes.length) }), 'success', 10000)
    } catch (err) {
      setView(v => (v.kind === 'export' ? { ...v, busy: false, error: String((err as Error).message ?? err) } : v))
    }
  }

  // ── Orphan view ──
  const orphanTarget = view.kind === 'orphan' ? targets.find(p => p.id === view.target) ?? targets[0] ?? null : null
  const orphanArchives = orphan ? backupsByProject[orphan.id] : undefined

  useConnectKeys((input, key) => {
    if (confirmKey(confirm, input, key, () => setConfirm(null))) return true

    if (view.kind === 'export') {
      if (key.escape) {
        if (!view.busy) setView({ kind: 'project', id: view.id, index: 0, top: 0 })
        return true
      }
      if (view.busy) return true
      if (key.return) {
        const target = view.path.text.trim()
        if (!target) setView({ ...view, error: t('apps.exportPathRequired') })
        else if (project) void exportZip(project, target)
        return true
      }
      const next = fieldKey(view.path, input, key)
      if (next) setView({ ...view, path: next, error: '' })
      return true
    }

    if (view.kind === 'project' && project) {
      const current = rows[rowIndex]
      const adjustable = current?.kind === 'interval' || current?.kind === 'keep'
      if (key.escape || (key.leftArrow && !adjustable)) {
        setView({ kind: 'list' })
        return true
      }
      const step = (delta: number) => {
        let i = rowIndex
        for (;;) {
          const next = i + delta
          if (next < 0 || next >= rows.length) break
          i = next
          if (selectable(rows[i])) break
        }
        if (!selectable(rows[i])) return
        const top = i < view.top ? i : i >= view.top + detailHeight ? i - detailHeight + 1 : view.top
        setView({ ...view, index: i, top: Math.max(0, top) })
      }
      if (key.upArrow || input === 'k') {
        step(-1)
        return true
      }
      if (key.downArrow || input === 'j') {
        step(1)
        return true
      }
      if (input === 'g') {
        setView({ ...view, index: Math.max(0, firstSelectable), top: 0 })
        return true
      }
      const row = rows[rowIndex]
      if (!row) return false
      if (row.kind === 'toggle' && (key.return || input === ' ')) {
        changeSetting(project, row.setting, !row.value)
        return true
      }
      if (row.kind === 'interval' && (key.return || input === ' ' || key.leftArrow || key.rightArrow || input === 'h' || input === 'l')) {
        const at = INTERVALS.indexOf(row.value as (typeof INTERVALS)[number])
        const delta = input === 'h' || key.leftArrow ? -1 : 1
        changeSetting(project, 'backupInterval', INTERVALS[(Math.max(0, at) + delta + INTERVALS.length) % INTERVALS.length])
        return true
      }
      if (row.kind === 'keep' && (key.leftArrow || key.rightArrow || input === 'l' || input === '+' || input === 'h' || input === '-')) {
        const next = Math.min(30, Math.max(1, row.value + (input === 'h' || input === '-' || key.leftArrow ? -1 : 1)))
        if (next !== row.value) changeSetting(project, 'backupKeep', next)
        return true
      }
      if (row.kind === 'action' && (key.return || input === ' ')) {
        runAction(project, row.id)
        return true
      }
      if (row.kind === 'info' && input === 'c' && row.copy) {
        copy(row.copy, row.label)
        return true
      }
      if (row.kind === 'backup') {
        if (key.return) {
          if (!backupBusy[project.id]) restore(project, row.entry)
          return true
        }
        if (input === 'd') {
          const entry = row.entry
          setConfirm({
            message: t('apps.confirmDeleteBackup', { date: when(entry.ts) }),
            onConfirm: () => send('agent_app_backup_delete', { projectId: project.id, filename: entry.filename }),
          })
          return true
        }
      }
      if (row.kind === 'share') {
        if (key.return) {
          if (row.link) copy(row.link, t(`apps.channel.${row.channel}`))
          else if (!shares[project.id]?.pending) openShare(project, row.channel)
          return true
        }
        if (input === 'c' && row.link) {
          copy(row.link, t(`apps.channel.${row.channel}`))
          return true
        }
        if (input === 'o' && row.link) {
          void openExternal(row.link).then(ok => showNotice(ok ? t('apps.opened') : t('apps.openFailed'), ok ? 'info' : 'error'))
          return true
        }
        if (input === 'x' && row.link) {
          send('agent_app_share_close', { projectId: project.id, channel: row.channel })
          return true
        }
      }
      return false
    }

    if (view.kind === 'orphan' && orphan) {
      const archives = orphanArchives ?? []
      if (key.escape) {
        setView({ kind: 'list' })
        return true
      }
      if (key.upArrow || input === 'k') {
        setView({ ...view, index: Math.max(0, view.index - 1) })
        return true
      }
      if (key.downArrow || input === 'j') {
        setView({ ...view, index: Math.min(Math.max(0, archives.length - 1), view.index + 1) })
        return true
      }
      if ((key.leftArrow || key.rightArrow || input === 't') && targets.length > 0) {
        const at = Math.max(0, targets.findIndex(p => p.id === orphanTarget?.id))
        const next = targets[(at + (key.leftArrow ? -1 : 1) + targets.length) % targets.length]
        setView({ ...view, target: next.id })
        return true
      }
      if (input === 'D') {
        setConfirm({
          message: t('apps.confirmDeleteLeftovers', { name: orphan.name }),
          onConfirm: () => {
            send('agent_app_backup_delete', { projectId: orphan.id, filename: '', orphan: true })
            send('agent_app_settings_get')
            setView({ kind: 'list' })
          },
        })
        return true
      }
      const entry = archives[view.index]
      if (!entry) return false
      if (key.return && orphanTarget) {
        const target = orphanTarget
        if (backupBusy[target.id]) return true
        setConfirm({
          message: t('apps.confirmRestoreInto', { date: when(entry.ts), name: orphan.name, target: target.name }),
          onConfirm: () => {
            setRestoring(target.id)
            dispatch(setBackupBusy({ projectId: target.id, busy: true }))
            send('agent_app_backup_restore', { projectId: target.id, filename: entry.filename, sourceProjectId: orphan.id })
          },
        })
        return true
      }
      if (input === 'd') {
        setConfirm({
          message: t('apps.confirmDeleteOrphanBackup', { date: when(entry.ts), name: orphan.name }),
          onConfirm: () => send('agent_app_backup_delete', { projectId: orphan.id, filename: entry.filename }),
        })
        return true
      }
      return false
    }

    // List: projects, then leftover backups.
    const count = projects.length + orphans.length
    const moved = listKey(listView, input, key, count, listHeight)
    if (moved) {
      setList(moved)
      return true
    }
    if (input === 'r') {
      send('agent_app_settings_get')
      showNotice(t('apps.refreshing'))
      return true
    }
    const index = listView.index
    if (index < projects.length) {
      const p = projects[index]
      if (!p) return false
      if (key.return || input === 'l' || key.rightArrow) {
        setView({ kind: 'project', id: p.id, index: 0, top: 0 })
        return true
      }
      if (input === 's') {
        if (p.status === 'running') runAction(p, 'stop')
        else if (['created', 'stopped', 'ready', 'error'].includes(p.status)) runAction(p, 'launch')
        return true
      }
      return false
    }
    const o = orphans[index - projects.length]
    if (o && (key.return || input === 'l' || key.rightArrow)) {
      setView({ kind: 'orphan', id: o.id, index: 0, target: null })
      return true
    }
    return false
  })

  const selectedRow = rows[rowIndex]
  useHints(
    view.kind === 'export'
      ? [
          { keys: 'Enter', label: t('apps.hintSave') },
          { keys: 'Esc', label: t('hint.cancel') },
        ]
      : view.kind === 'project'
        ? [
            { keys: 'j/k', label: t('hint.move') },
            ...(selectedRow?.kind === 'toggle' ? [{ keys: 'Space', label: t('hint.toggle') }] : []),
            ...(selectedRow?.kind === 'interval' || selectedRow?.kind === 'keep' ? [{ keys: '←/→', label: t('apps.hintChange') }] : []),
            ...(selectedRow?.kind === 'action' ? [{ keys: 'Enter', label: t('apps.hintRun') }] : []),
            ...(selectedRow?.kind === 'info' && selectedRow.copy ? [{ keys: 'c', label: t('apps.hintCopy') }] : []),
            ...(selectedRow?.kind === 'backup'
              ? [
                  { keys: 'Enter', label: t('apps.hintRestore') },
                  { keys: 'd', label: t('hint.delete') },
                ]
              : []),
            ...(selectedRow?.kind === 'share'
              ? selectedRow.link
                ? [
                    { keys: 'c', label: t('apps.hintCopy') },
                    { keys: 'o', label: t('apps.hintOpen') },
                    { keys: 'x', label: t('apps.hintCloseLink') },
                  ]
                : [{ keys: 'Enter', label: t('apps.hintCreateLink') }]
              : []),
            { keys: 'Esc', label: t('hint.back') },
          ]
        : view.kind === 'orphan'
          ? [
              { keys: 'Enter', label: t('apps.hintRestore') },
              { keys: '←/→', label: t('apps.hintTarget') },
              { keys: 'd', label: t('hint.delete') },
              { keys: 'D', label: t('apps.hintDeleteAll') },
              { keys: 'Esc', label: t('hint.back') },
            ]
          : [
              { keys: 'Enter', label: t('hint.open') },
              { keys: 's', label: t('apps.hintStartStop') },
              { keys: 'r', label: t('hint.reload') },
            ],
  )

  const g = glyphs()
  const footer = confirm ? <ConfirmBlock pending={confirm} width={width} hint={t('common.confirmHint')} /> : <NoticeLine notice={notice} width={width} />

  if (view.kind === 'export' && project) {
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(t('apps.exportTitle', { name: project.name }), width - 1)}</Text>
        <Text color={ink.muted}>{truncate(t('apps.exportDesc'), width - 1)}</Text>
        <Text> </Text>
        <TextField label={t('apps.exportPath')} buffer={view.path} focused={active && !view.busy} width={width - 1} />
        <Text> </Text>
        {view.busy ? <Text color={ink.muted}>{`${spinner} ${t('apps.exporting')}`}</Text> : null}
        {view.error ? <Text color={ink.error}>{truncate(view.error, width - 1)}</Text> : null}
      </Box>
    )
  }

  if (view.kind === 'project' && project) {
    const [mark, markColor] = statusMark(project.status)
    const labelWidth = Math.min(22, Math.max(...rows.map(r => ('label' in r && r.kind !== 'heading' && r.kind !== 'text' && r.kind !== 'action' ? cells(r.label) : 0)), 8) + 1)
    const top = Math.min(view.top, Math.max(0, rows.length - detailHeight))
    return (
      <Box flexDirection="column">
        <Box>
          <Text bold color={ink.brand}>{truncate(project.name, Math.max(8, width - 24))}</Text>
          <Text color={markColor}>{`  ${mark} ${statusText(project.status)}`}</Text>
          {inProgress === project.id ? <Text color={ink.muted}>{` ${spinner}`}</Text> : null}
        </Box>
        {rows.slice(top, top + detailHeight).map((row, i) => {
          const index = top + i
          const on = active && index === rowIndex
          const pointer = on ? `${g.pointer} ` : '  '
          const room = width - labelWidth - 4
          switch (row.kind) {
            case 'heading':
              return <Text key={index} color={ink.muted} bold>{truncate(row.label, width - 1)}</Text>
            case 'text':
              return <Text key={index} color={row.color}>{truncate(`  ${row.label}`, width - 1)}</Text>
            case 'info':
              return (
                <Text key={index} color={on ? ink.focus : undefined}>
                  {pointer}
                  <Text color={ink.muted}>{padEnd(row.label, labelWidth)} </Text>
                  {truncate(row.value, room, 'middle')}
                </Text>
              )
            case 'toggle':
              return (
                <Text key={index} color={on ? ink.focus : undefined}>
                  {pointer}
                  <Text color={ink.muted}>{padEnd(row.label, labelWidth)} </Text>
                  {row.value ? `${g.checked} ${t('common.on')}` : `${g.unchecked} ${t('common.off')}`}
                </Text>
              )
            case 'interval':
              return (
                <Text key={index} color={on ? ink.focus : undefined}>
                  {pointer}
                  <Text color={ink.muted}>{padEnd(row.label, labelWidth)} </Text>
                  {on ? `< ${t(`apps.interval.${row.value}`)} >` : t(`apps.interval.${row.value}`)}
                </Text>
              )
            case 'keep':
              return (
                <Text key={index} color={on ? ink.focus : undefined}>
                  {pointer}
                  <Text color={ink.muted}>{padEnd(row.label, labelWidth)} </Text>
                  {on ? `< ${row.value} >` : String(row.value)}
                </Text>
              )
            case 'action':
              return (
                <Text key={index} color={on ? ink.focus : row.danger ? ink.error : undefined} bold={on}>
                  {pointer}
                  {`[ ${row.label} ]`}
                </Text>
              )
            case 'backup':
              return (
                <Text key={index} color={on ? ink.focus : undefined}>
                  {pointer}
                  {truncate(backupLabel(row.entry), width - 3)}
                </Text>
              )
            case 'share': {
              const pendingShare = shares[project.id]?.pending === row.channel
              const label = t(`apps.channel.${row.channel}`)
              const value = row.link ?? (pendingShare ? `${spinner} ${t('apps.starting')}` : t(`apps.channelHint.${row.channel}`))
              return (
                <Text key={index} color={on ? ink.focus : undefined}>
                  {pointer}
                  <Text color={ink.muted}>{padEnd(label, labelWidth)} </Text>
                  <Text color={row.link ? undefined : ink.muted}>{truncate(value, room, row.link ? 'middle' : 'end')}</Text>
                </Text>
              )
            }
          }
        })}
        {footer}
      </Box>
    )
  }

  if (view.kind === 'orphan' && orphan) {
    const archives = orphanArchives
    const busy = orphanTarget ? backupBusy[orphanTarget.id] : false
    const result = orphanTarget ? restoreResult[orphanTarget.id] : undefined
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(t('apps.leftoverTitle', { name: orphan.name }), width - 1)}</Text>
        <Text color={ink.muted}>
          {truncate(orphanTarget ? t('apps.restoreTarget', { name: orphanTarget.name }) : t('apps.noRestoreTarget'), width - 1)}
        </Text>
        {busy ? <Text color={ink.muted}>{`${spinner} ${t('apps.restoringInto', { name: orphanTarget?.name ?? '' })}`}</Text> : null}
        {result && !busy ? <Text color={result.ok ? ink.success : ink.error}>{truncate(result.message, width - 1)}</Text> : null}
        {archives === undefined ? <Text color={ink.muted}>{t('common.loading')}</Text> : null}
        {archives && archives.length === 0 ? <Text color={ink.muted}>{t('apps.noArchives')}</Text> : null}
        {(archives ?? []).slice(0, Math.max(3, height - 5)).map((entry, i) => (
          <Row
            key={entry.filename}
            selected={active && i === view.index}
            mark={g.artifact}
            markColor={ink.muted}
            label={backupLabel(entry)}
            width={width}
          />
        ))}
        {footer}
      </Box>
    )
  }

  // ── List ──
  const running_ = projects.filter(p => p.status === 'running').length
  const listItems: ({ type: 'project'; project: AgentAppSettingsProject } | { type: 'orphan'; orphan: AgentAppBackupOrphan })[] = [
    ...projects.map(p => ({ type: 'project' as const, project: p })),
    ...orphans.map(o => ({ type: 'orphan' as const, orphan: o })),
  ]
  const selectedItem = listItems[listView.index]
  return (
    <Box flexDirection="column">
      <Text color={ink.muted}>
        {truncate(hasLoaded ? t('apps.summary', { count: projects.length, running: running_ }) : t('common.loading'), width - 1)}
      </Text>
      {hasLoaded && projects.length === 0 ? <Text color={ink.muted}>{truncate(t('apps.none'), width - 1)}</Text> : null}
      {listItems.slice(listView.top, listView.top + listHeight).map((item, i) => {
        const index = listView.top + i
        const selectedNow = active && index === listView.index
        if (item.type === 'project') {
          const p = item.project
          const [mark, color] = statusMark(p.status)
          return (
            <Row
              key={p.id}
              selected={selectedNow}
              mark={inProgress === p.id ? spinner || mark : mark}
              markColor={color}
              label={p.name}
              dim={!isActive(p.status)}
              aside={[statusText(p.status), p.port != null ? `:${p.port}` : ''].filter(Boolean).join(' ')}
              width={width}
            />
          )
        }
        const o = item.orphan
        const first = index === projects.length
        return (
          <Box key={`orphan-${o.id}`} flexDirection="column">
            {first ? <Text color={ink.muted} bold>{truncate(t('apps.leftoverHeading'), width - 1)}</Text> : null}
            <Row selected={selectedNow} mark={g.artifact} markColor={ink.muted} label={o.name} aside={o.name !== o.id ? o.id : ''} width={width} dim />
          </Box>
        )
      })}
      {selectedItem?.type === 'project' ? (
        <Box marginTop={1}>
          <Text color={ink.muted}>{truncate(selectedItem.project.path, width - 1, 'middle')}</Text>
        </Box>
      ) : selectedItem?.type === 'orphan' ? (
        <Box marginTop={1}>
          <Text color={ink.muted}>{truncate(t('apps.leftoverDesc'), width - 1)}</Text>
        </Box>
      ) : null}
      {footer}
    </Box>
  )
}
