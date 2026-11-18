/**
 * Every Agent App, in the browser sidebar's saved order: the apps the
 * framework has registered (installed here, or connected by URL), then the
 * builds still being made. Each row has a status glyph and word and a mark
 * while your AI agent is working in the app's own chat.
 *
 * Keys: Enter opens the app, l starts it, s stops it, d deletes it (or
 * disconnects a connected app, confirmed first), t picks a theme, p opens its
 * settings, a opens Add Agent App, J/K move it down or up the list, r reads
 * the registry again. Starting runs the app's server and nothing else: no
 * browser opens.
 */
import { useMemo, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { setUiState } from '../../../../browser/frontend/src/store/slices/uiSlice'
import { selectUiState } from '../../../../browser/frontend/src/store/selectors/ui'
import { UI_STATE } from '../../../../browser/frontend/src/store/uiState'
import { RESOURCES, useResource } from '../../../../browser/frontend/src/store/resources'
import { selectFrameworkAppSessionIds } from '../../../../browser/frontend/src/store/selectors/sessions'
import { useAppDispatch, useAppSelector } from '../../state/hooks'
import { openScreen } from '../../state/tuiSlice'
import { Frame, bodyRows, type KeyHint } from '../../ui/Frame'
import { useScreen, useScreenKeys } from '../context'
import { clampList, listKey, LIST_START } from '../../ui/list'
import { useTicker } from '../../ui/useTicker'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { padEnd, truncate, width } from '../../text/width'
import {
  appPhase,
  canChangeState,
  changeAppState,
  errorText,
  frameworkAppKey,
  isTransitional,
  moveId,
  orderEntries,
  orderIdOf,
  pendingBuilds,
  pendingOrderId,
  requestAppList,
  type AppEntry,
  type AppPhase,
  type RegistryApp,
} from '../../apps/framework'
import { removeApp, removalKind } from '../../apps/removal'
import { deriveProgress } from './hostModel'
import {
  applyTheme,
  appThemeId,
  openThemePicker,
  pickerListHeight,
  themeName,
  themePickerKey,
  ThemePicker,
  type ThemePickerState,
} from './hostThemes'
import { AppSettingsPanel, useAppSettingsKeys } from './AppSettingsPanel'

type Mode = { kind: 'list' } | { kind: 'theme'; picker: ThemePickerState } | { kind: 'settings' }
type Confirm = { app: RegistryApp; keepFiles: boolean; message: string }

const PHASE_COLOR: Record<AppPhase | 'building', string | undefined> = {
  building: ink.brand,
  starting: ink.brand,
  stopping: ink.warn,
  running: ink.success,
  stopped: ink.muted,
  missing: ink.error,
  unreachable: ink.error,
}

export function AppsScreen(_props: { arg?: string }) {
  const { t } = useTranslation('appsHost')
  const dispatch = useAppDispatch()
  const { columns, rows } = useScreen()
  useResource(RESOURCES.agentAppsList)
  const registry = useAppSelector(s => s.agentApp.framework)
  const lifecycle = useAppSelector(s => s.agentApp.frameworkLifecycle)
  const pending = useAppSelector(pendingBuilds)
  const boundSessions = useAppSelector(selectFrameworkAppSessionIds)
  const sessionIds = useAppSelector(s => s.agentApp.frameworkSessions)
  const connected = useAppSelector(s => s.connection.connected)
  const order = useAppSelector(s => selectUiState(s, UI_STATE.nav.agentAppOrder))
  const runState = useAppSelector(s => s.agent.runStateBySession)
  const todos = useAppSelector(s => s.agentApp.todos)

  const entries = useMemo(() => {
    const all: AppEntry[] = [
      ...(registry.apps as RegistryApp[]).map(app => ({ kind: 'app' as const, orderId: orderIdOf(app), app })),
      ...pending.map(session => ({ kind: 'pending' as const, orderId: pendingOrderId(session.id), session })),
    ]
    return orderEntries(all, order)
  }, [registry.apps, pending, order])

  const [list, setList] = useState(LIST_START)
  const [mode, setMode] = useState<Mode>({ kind: 'list' })
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const [notice, setNotice] = useState<{ text: string; error?: boolean } | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)

  const body = bodyRows(rows)
  // The list leaves room for the selected app's details (three lines) and a status line.
  const height = Math.max(1, body - 6)
  const view = clampList(list, entries.length, height)
  const selected: AppEntry | undefined = entries[view.index]
  const selectedApp = selected?.kind === 'app' ? selected.app : undefined
  const job = selectedApp ? lifecycle[frameworkAppKey(selectedApp.path, selectedApp.id)] : undefined
  const phase = selectedApp ? appPhase(selectedApp, job) : undefined
  const anyMoving = pending.length > 0 || entries.some(e => e.kind === 'app' && isTransitional(appPhase(e.app, lifecycle[frameworkAppKey(e.app.path, e.app.id)])))
  const tick = useTicker(120, anyMoving)
  const settingsKey = useAppSettingsKeys(selectedApp, () => setMode({ kind: 'list' }))
  const stale = !connected || registry.status !== 'success'

  const sessionOf = (entry: AppEntry): string | undefined => {
    if (entry.kind === 'pending') return entry.session.id
    return sessionIds[frameworkAppKey(entry.app.path, entry.app.id)] ?? boundSessions[entry.orderId]
  }

  const reorder = (delta: -1 | 1) => {
    if (!selected) return
    const ids = entries.map(e => e.orderId)
    const next = moveId(ids, selected.orderId, delta)
    if (next === ids) return
    dispatch(setUiState(UI_STATE.nav.agentAppOrder, next))
    setList(clampList({ ...view, index: view.index + delta }, entries.length, height))
  }

  const remove = (app: RegistryApp, keepFiles: boolean) => {
    setDeleting(frameworkAppKey(app.path, app.id))
    setNotice({ text: t('apps.deleting', { name: app.name }) })
    removeApp(app, keepFiles)
      .then(outcome => {
        if (outcome === 'needsKeepFiles') {
          setConfirm({ app, keepFiles: true, message: t('apps.confirmKeepFiles', { name: app.name }) })
          setNotice(null)
          return
        }
        setNotice({ text: t(`apps.${outcome}`, { name: app.name }) })
        requestAppList()
      })
      .catch(err => setNotice({ text: errorText(err), error: true }))
      .finally(() => setDeleting(null))
  }

  const askDelete = (app: RegistryApp) => {
    const kind = removalKind(app, false)
    const message =
      kind === 'disconnect'
        ? t('apps.confirmDisconnect', { name: app.name })
        : kind === 'forget'
          ? t('apps.confirmForget', { name: app.name })
          : t('apps.confirmDelete', { name: app.name })
    setConfirm({ app, keepFiles: false, message })
  }

  useScreenKeys((input, key) => {
    if (confirm) {
      if (input === 'y' || input === 'Y') remove(confirm.app, confirm.keepFiles)
      setConfirm(null)
      return true
    }
    if (mode.kind === 'settings') {
      if (settingsKey(input, key)) return true
      if (key.escape || key.leftArrow) {
        setMode({ kind: 'list' })
        return true
      }
      return false
    }
    if (mode.kind === 'theme') {
      const result = themePickerKey(mode.picker, input, key, pickerListHeight(body))
      if (result?.kind === 'move') setMode({ kind: 'theme', picker: result.state })
      else if (result?.kind === 'cancel') setMode({ kind: 'list' })
      else if (result?.kind === 'apply' && selectedApp) {
        const app = selectedApp
        setMode({ kind: 'list' })
        applyTheme(dispatch, app, result.themeId)
          .then(() => setNotice({ text: t('apps.themeSet', { name: app.name, theme: themeName(t, result.themeId) }) }))
          .catch(err => setNotice({ text: errorText(err), error: true }))
      }
      return true
    }

    if (input === 'J' || (key.shift && key.downArrow)) {
      reorder(1)
      return true
    }
    if (input === 'K' || (key.shift && key.upArrow)) {
      reorder(-1)
      return true
    }
    const moved = listKey(view, input, key, entries.length, height)
    if (moved) {
      setList(moved)
      return true
    }
    setNotice(null)
    if (input === 'a') {
      dispatch(openScreen({ id: 'appCreate' }))
      return true
    }
    if (input === 'r') {
      requestAppList()
      return true
    }
    if (!selected) return false
    if (key.return || key.rightArrow) {
      const arg = selected.kind === 'app' ? frameworkAppKey(selected.app.path, selected.app.id) : pendingOrderId(selected.session.id)
      dispatch(openScreen({ id: 'app', arg }))
      return true
    }
    if (!selectedApp || !phase) return false
    const busy = isTransitional(phase) || deleting === frameworkAppKey(selectedApp.path, selectedApp.id)
    if (input === 'l' || input === 's') {
      const operation = input === 'l' ? 'start' : 'stop'
      if (stale) setNotice({ text: t('apps.stale'), error: true })
      else if (busy) setNotice({ text: t('apps.busy', { name: selectedApp.name }) })
      else if (!canChangeState(selectedApp)) setNotice({ text: t(selectedApp.connection ? 'apps.remoteNoLifecycle' : 'apps.cannotChange', { name: selectedApp.name }) })
      else if (operation === 'start' && phase === 'running') setNotice({ text: t('apps.alreadyRunning', { name: selectedApp.name }) })
      else if (operation === 'stop' && phase !== 'running') setNotice({ text: t('apps.notRunning', { name: selectedApp.name }) })
      else if (!changeAppState(dispatch, selectedApp, operation)) setNotice({ text: t('apps.stale'), error: true })
      return true
    }
    if (input === 'd') {
      if (stale) setNotice({ text: t('apps.stale'), error: true })
      else if (busy) setNotice({ text: t('apps.busy', { name: selectedApp.name }) })
      else askDelete(selectedApp)
      return true
    }
    if (input === 't' && !selectedApp.connection && selectedApp.status !== 'missing') {
      setMode({ kind: 'theme', picker: openThemePicker(appThemeId(selectedApp)) })
      return true
    }
    if (input === 'p') {
      setMode({ kind: 'settings' })
      return true
    }
    return false
  })

  const g = glyphs()
  const spinner = spinnerFrames()
  const running = (registry.apps as RegistryApp[]).filter(a => a.status === 'running').length
  const aside = entries.length ? `${t('apps.count', { count: entries.length })} ${g.sep} ${t('apps.running', { count: running })}` : ''

  let title = t('apps.title')
  let hints: KeyHint[]
  if (mode.kind === 'settings' && selectedApp) {
    title = `${t('apps.title')} › ${selectedApp.name} › ${t('apps.settings')}`
    hints = [{ keys: 'Esc', label: t('hint.back') }]
  } else if (mode.kind === 'theme') {
    hints = [
      { keys: 'Enter', label: t('hint.apply') },
      { keys: 'j/k', label: t('hint.move') },
      { keys: 'Esc', label: t('hint.cancel') },
    ]
  } else {
    const changeable = selectedApp && canChangeState(selectedApp) && phase && !isTransitional(phase)
    hints = [
      ...(selected ? [{ keys: 'Enter', label: t('hint.open') }] : []),
      { keys: 'a', label: t('hint.add') },
      ...(changeable && phase !== 'running' ? [{ keys: 'l', label: t('hint.launch') }] : []),
      ...(changeable && phase === 'running' ? [{ keys: 's', label: t('hint.stop') }] : []),
      ...(selectedApp && !selectedApp.connection ? [{ keys: 't', label: t('hint.theme') }] : []),
      ...(selectedApp ? [{ keys: 'p', label: t('hint.settings') }, { keys: 'd', label: selectedApp.connection ? t('hint.disconnect') : t('hint.delete') }] : []),
      ...(entries.length > 1 ? [{ keys: 'J/K', label: t('hint.reorder') }] : []),
      { keys: 'Esc', label: t('hint.back') },
    ]
  }

  // Columns: pointer 2, glyph 2, name, agent mark 2, status word, port or "remote".
  const statusWidth = 13
  const portWidth = 8
  const nameWidth = Math.max(8, columns - 2 - 2 - 2 - statusWidth - portWidth)

  const statusWord = (entry: AppEntry): { word: string; phase: AppPhase | 'building' } => {
    if (entry.kind === 'pending') return { word: t('status.building'), phase: 'building' }
    const p = appPhase(entry.app, lifecycle[frameworkAppKey(entry.app.path, entry.app.id)])
    if (entry.app.connection && !isTransitional(p)) {
      return { word: t(`status.connection.${entry.app.connection.status}`, { defaultValue: entry.app.connection.status }), phase: p }
    }
    const word = t(`status.${p}`)
    return { word: stale ? t('apps.lastKnown', { status: word }) : word, phase: p }
  }

  const renderList = () => {
    if (entries.length === 0) {
      if (!connected) return <Text color={ink.muted}>{truncate(t('apps.disconnected'), columns)}</Text>
      if (!registry.hasSnapshot && registry.status !== 'error') return <Text color={ink.muted}>{truncate(t('apps.loading'), columns)}</Text>
      return (
        <Box flexDirection="column">
          <Text>{truncate(t('apps.empty'), columns)}</Text>
          <Text color={ink.muted}>{truncate(t('apps.emptyHint'), columns)}</Text>
        </Box>
      )
    }
    return (
      <Box flexDirection="column">
        {entries.slice(view.top, view.top + height).map((entry, i) => {
          const isSelected = view.top + i === view.index
          const { word, phase: p } = statusWord(entry)
          const moving = p === 'building' || isTransitional(p as AppPhase)
          const glyph = moving ? spinner[tick % spinner.length] : p === 'running' ? g.unread : p === 'missing' || p === 'unreachable' ? g.failed : g.idle
          const name = entry.kind === 'app' ? entry.app.name : entry.session.title || t('apps.newBuild')
          const sid = sessionOf(entry)
          const working = !!sid && runState[sid] !== undefined
          const port = entry.kind === 'app' ? (entry.app.connection ? t('apps.remote') : entry.app.port ? `:${entry.app.port}` : '') : ''
          return (
            <Box key={entry.orderId}>
              <Text color={isSelected ? ink.focus : undefined}>{isSelected ? `${g.pointer} ` : '  '}</Text>
              <Text color={PHASE_COLOR[p]}>{glyph} </Text>
              <Text bold={isSelected} color={p === 'stopped' && !isSelected ? ink.muted : undefined}>{padEnd(truncate(name, nameWidth), nameWidth)}</Text>
              <Text color={ink.brand}>{working ? `${g.busy} ` : '  '}</Text>
              <Text color={PHASE_COLOR[p]}>{padEnd(truncate(word, statusWidth - 1), statusWidth)}</Text>
              <Text color={ink.muted}>{padEnd(port, portWidth)}</Text>
            </Box>
          )
        })}
      </Box>
    )
  }

  // Details of the selected row: where it is, what it is doing, what went wrong.
  const renderDetails = () => {
    if (!selected) return null
    const lines: { text: string; color?: string }[] = []
    if (selected.kind === 'pending') {
      const build = selected.session.agentAppBuild
      const checkpoint = build?.checkpoint
      if (checkpoint && checkpoint.status === 'pending' && checkpoint.shown === 'ui') {
        lines.push({ text: t(checkpoint.kind === 'questions' ? 'apps.waitingAnswers' : 'apps.waitingReview'), color: ink.warn })
      } else {
        const progress = deriveProgress(todos[`framework-build:${selected.session.id}`] ?? build?.todos)
        lines.push({
          text: progress.total
            ? t('apps.building', { current: Math.min(progress.total, progress.done + 1), total: progress.total, step: progress.label || t('apps.buildingStep') })
            : t('apps.buildingStart'),
        })
      }
      lines.push({ text: t('apps.openBuildHint'), color: ink.muted })
    } else {
      const app = selected.app
      lines.push({ text: app.connection ? app.connection.origin : app.path, color: ink.muted })
      if (job?.status === 'running' && job.message) lines.push({ text: job.message })
      else if (job?.status === 'error') lines.push({ text: job.message || t('apps.lifecycleFailed'), color: ink.error })
      else if (job?.status === 'unknown') lines.push({ text: t('apps.lifecycleUnknown'), color: ink.warn })
      else if (job?.remaining && job.operation === 'stop') lines.push({ text: t('apps.remaining'), color: ink.muted })
      else if (phase === 'running' && app.url) lines.push({ text: t('apps.runningAt', { url: app.url }) })
      else if (phase === 'missing') lines.push({ text: t('apps.missingHint'), color: ink.error })
      else if (phase === 'unreachable') lines.push({ text: t('apps.unreachableHint'), color: ink.error })
      const sid = sessionOf(selected)
      const extras = [
        sid && runState[sid] !== undefined ? t('apps.agentWorking') : '',
        !app.connection ? t('apps.themeLine', { theme: themeName(t, appThemeId(app)) }) : app.connection.principalName ? t('apps.signedInAs', { name: app.connection.principalName }) : '',
      ].filter(Boolean)
      if (extras.length) lines.push({ text: extras.join(` ${g.sep} `), color: ink.muted })
    }
    return lines.slice(0, 3).map((line, i) => (
      <Text key={i} color={line.color}>{truncate(line.text, columns)}</Text>
    ))
  }

  const registryNotice = !connected
    ? { text: t('apps.disconnected'), color: ink.warn }
    : registry.status === 'error'
      ? { text: t('apps.registryFailed', { error: registry.error ?? '' }), color: ink.error }
      : registry.warning
        ? { text: t('apps.registryWarning', { warning: registry.warning.split('\n')[0] }), color: ink.warn }
        : null

  return (
    <Frame title={title} aside={mode.kind === 'list' ? aside : ''} hints={hints} columns={columns} rows={rows}>
      {mode.kind === 'settings' && selectedApp ? (
        <AppSettingsPanel app={selectedApp} columns={columns} rows={body} active onDeleted={() => setMode({ kind: 'list' })} />
      ) : mode.kind === 'theme' && selectedApp ? (
        <ThemePicker
          t={t}
          state={mode.picker}
          currentId={appThemeId(selectedApp)}
          title={t('theme.title', { name: selectedApp.name })}
          columns={columns}
          rows={body}
        />
      ) : (
        <Box flexDirection="column">
          {registryNotice && entries.length > 0 ? <Text color={registryNotice.color}>{truncate(registryNotice.text, columns)}</Text> : null}
          {renderList()}
          {entries.length > 0 ? <Text> </Text> : null}
          {renderDetails()}
          {confirm ? (
            <Box>
              <Text color={ink.warn} bold>{truncate(confirm.message, Math.max(10, columns - width(t('hint.confirm')) - 2))}</Text>
              <Text color={ink.muted}>{'  ' + t('hint.confirm')}</Text>
            </Box>
          ) : notice ? (
            <Text color={notice.error ? ink.error : ink.info}>{truncate(notice.text, columns)}</Text>
          ) : null}
        </Box>
      )}
    </Frame>
  )
}
