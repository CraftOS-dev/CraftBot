/**
 * Every Agent App, in the browser sidebar's saved order, with a status glyph
 * and word (creating, launching, running, stopping, stopped, error) and a
 * mark while your AI agent is working in the app's own chat.
 *
 * Keys: Enter opens the app, l launches, s stops, d deletes (with a
 * confirmation, only while stopped), t picks a theme pack, p opens the app's
 * settings, a opens Add Agent App, J/K move the app down or up the list.
 * Launching starts the app's server and nothing else: no browser opens.
 */
import { useMemo, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { AgentAppProject } from '../../../../browser/frontend/src/types'
import { markLaunching, markStopping } from '../../../../browser/frontend/src/store/slices/agentAppSlice'
import { setUiState } from '../../../../browser/frontend/src/store/slices/uiSlice'
import { selectUiState } from '../../../../browser/frontend/src/store/selectors/ui'
import { UI_STATE } from '../../../../browser/frontend/src/store/uiState'
import { RESOURCES, useResource } from '../../../../browser/frontend/src/store/resources'
import { send, useAppDispatch, useAppSelector } from '../../state/hooks'
import { openScreen } from '../../state/tuiSlice'
import { Frame, bodyRows, type KeyHint } from '../../ui/Frame'
import { useScreen, useScreenKeys } from '../context'
import { clampList, listKey, LIST_START } from '../../ui/list'
import { useTicker } from '../../ui/useTicker'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { oneLine, padEnd, truncate, width, wrap } from '../../text/width'
import {
  appPhase,
  canDelete,
  canLaunch,
  canStop,
  deriveProgress,
  isTransitional,
  moveId,
  orderApps,
  type AppPhase,
} from './hostModel'
import {
  applyTheme,
  openThemePicker,
  pickerListHeight,
  projectThemeId,
  themeName,
  themePickerKey,
  ThemePicker,
  type ThemePickerState,
} from './hostThemes'
import { AppSettingsPanel, useAppSettingsKeys } from './AppSettingsPanel'

type Mode = { kind: 'list' } | { kind: 'theme'; picker: ThemePickerState } | { kind: 'settings' }

const PHASE_COLOR: Record<AppPhase, string | undefined> = {
  creating: ink.brand,
  launching: ink.brand,
  stopping: ink.warn,
  running: ink.success,
  stopped: ink.muted,
  error: ink.error,
}

function iconName(icon: string | null | undefined): string {
  return icon?.startsWith('lucide:') ? icon.slice(7) : ''
}

export function AppsScreen(_props: { arg?: string }) {
  const { t } = useTranslation('appsHost')
  const dispatch = useAppDispatch()
  const { columns, rows } = useScreen()
  useResource(RESOURCES.agentAppsList)
  const projects = useAppSelector(s => s.agentApp.projects)
  const order = useAppSelector(s => selectUiState(s, UI_STATE.nav.agentAppOrder))
  const runState = useAppSelector(s => s.agent.runStateBySession)
  const todos = useAppSelector(s => s.agentApp.todos)
  const apps = useMemo(() => orderApps(projects, order), [projects, order])

  const [list, setList] = useState(LIST_START)
  const [mode, setMode] = useState<Mode>({ kind: 'list' })
  const [confirm, setConfirm] = useState<{ projectId: string; message: string } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const body = bodyRows(rows)
  // The list leaves room for the selected app's details (three lines) and a status line.
  const height = Math.max(1, body - 5)
  const view = clampList(list, apps.length, height)
  const selected: AgentAppProject | undefined = apps[view.index]
  const phase = appPhase(selected?.status)
  const anyTransitional = apps.some(p => isTransitional(appPhase(p.status)))
  const tick = useTicker(120, anyTransitional)
  const settingsKey = useAppSettingsKeys(selected?.id ?? '')

  const launch = (project: AgentAppProject) => {
    dispatch(markLaunching({ projectId: project.id }))
    send('agent_app_launch', { projectId: project.id })
  }
  const stop = (project: AgentAppProject) => {
    dispatch(markStopping({ projectId: project.id }))
    send('agent_app_stop', { projectId: project.id })
  }
  const reorder = (delta: -1 | 1) => {
    if (!selected) return
    const ids = apps.map(p => p.id)
    const next = moveId(ids, selected.id, delta)
    if (next === ids) return
    dispatch(setUiState(UI_STATE.nav.agentAppOrder, next))
    setList(clampList({ ...view, index: view.index + delta }, apps.length, height))
  }

  useScreenKeys((input, key) => {
    if (confirm) {
      if (input === 'y' || input === 'Y') send('agent_app_delete', { projectId: confirm.projectId })
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
      else if (result?.kind === 'apply') {
        if (selected) applyTheme(dispatch, selected, result.themeId)
        setNotice(selected ? t('apps.themeSet', { name: selected.name, theme: themeName(t, result.themeId) }) : null)
        setMode({ kind: 'list' })
      }
      return true
    }

    setNotice(null)
    if (input === 'J' || (key.shift && key.downArrow)) {
      reorder(1)
      return true
    }
    if (input === 'K' || (key.shift && key.upArrow)) {
      reorder(-1)
      return true
    }
    const moved = listKey(view, input, key, apps.length, height)
    if (moved) {
      setList(moved)
      return true
    }
    if (input === 'a') {
      dispatch(openScreen({ id: 'appCreate' }))
      return true
    }
    if (!selected) return false
    if (key.return || key.rightArrow) {
      dispatch(openScreen({ id: 'app', arg: selected.id }))
      return true
    }
    if (input === 'l') {
      if (canLaunch(phase)) launch(selected)
      else setNotice(phase === 'running' ? t('apps.alreadyRunning', { name: selected.name }) : t('apps.busy', { name: selected.name }))
      return true
    }
    if (input === 's') {
      if (canStop(phase)) stop(selected)
      else setNotice(t('apps.notRunning', { name: selected.name }))
      return true
    }
    if (input === 'd') {
      if (canDelete(phase)) setConfirm({ projectId: selected.id, message: t('apps.confirmDelete', { name: selected.name }) })
      else setNotice(phase === 'running' ? t('apps.stopFirst', { name: selected.name }) : t('apps.busy', { name: selected.name }))
      return true
    }
    if (input === 't') {
      setMode({ kind: 'theme', picker: openThemePicker(projectThemeId(selected)) })
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
  const running = apps.filter(p => appPhase(p.status) === 'running').length
  const aside = apps.length ? `${t('apps.count', { count: apps.length })} · ${t('apps.running', { count: running })}` : ''

  let title = t('apps.title')
  let hints: KeyHint[]
  if (mode.kind === 'settings' && selected) {
    title = `${t('apps.title')} › ${selected.name} › ${t('apps.settings')}`
    hints = [{ keys: 'Esc', label: t('hint.back') }]
  } else if (mode.kind === 'theme') {
    hints = [
      { keys: 'Enter', label: t('hint.apply') },
      { keys: 'j/k', label: t('hint.move') },
      { keys: 'Esc', label: t('hint.cancel') },
    ]
  } else {
    hints = [
      ...(selected ? [{ keys: 'Enter', label: t('hint.open') }] : []),
      { keys: 'a', label: t('hint.add') },
      ...(selected && canLaunch(phase) ? [{ keys: 'l', label: t('hint.launch') }] : []),
      ...(selected && canStop(phase) ? [{ keys: 's', label: t('hint.stop') }] : []),
      ...(selected ? [{ keys: 't', label: t('hint.theme') }, { keys: 'p', label: t('hint.settings') }] : []),
      ...(selected && canDelete(phase) ? [{ keys: 'd', label: t('hint.delete') }] : []),
      ...(apps.length > 1 ? [{ keys: 'J/K', label: t('hint.reorder') }] : []),
      { keys: 'Esc', label: t('hint.back') },
    ]
  }

  // Columns: pointer 2, glyph 2, name, status word, port, icon name (wide terminals).
  const statusWidth = 11
  const portWidth = 7
  const iconWidth = columns >= 100 ? 18 : 0
  const nameWidth = Math.max(8, columns - 2 - 2 - 2 - statusWidth - portWidth - iconWidth)

  const renderList = () => {
    if (apps.length === 0) {
      return (
        <Box flexDirection="column">
          <Text>{truncate(t('apps.empty'), columns)}</Text>
          {wrap(t('apps.emptyHint'), columns).map(l => l.trimStart()).map((line, i) => (
            <Text key={i} color={ink.muted}>{line}</Text>
          ))}
        </Box>
      )
    }
    return (
      <Box flexDirection="column">
        {apps.slice(view.top, view.top + height).map((project, i) => {
          const index = view.top + i
          const isSelected = index === view.index
          const p = appPhase(project.status)
          const glyph = isTransitional(p) ? spinner[tick % spinner.length] : p === 'running' ? g.unread : p === 'error' ? g.failed : g.idle
          const busy = !!project.sessionId && runState[project.sessionId] !== undefined
          const port = project.port && p === 'running' ? `:${project.port}` : ''
          return (
            <Box key={project.id}>
              <Text color={isSelected ? ink.focus : undefined}>{isSelected ? `${g.pointer} ` : '  '}</Text>
              <Text color={PHASE_COLOR[p]}>{glyph} </Text>
              <Text bold={isSelected} color={p === 'stopped' && !isSelected ? ink.muted : undefined}>{padEnd(project.name, nameWidth)}</Text>
              <Text color={ink.brand}>{busy ? `${g.busy} ` : '  '}</Text>
              <Text color={PHASE_COLOR[p]}>{padEnd(t(`status.${p}`), statusWidth)}</Text>
              <Text color={ink.muted}>{padEnd(port, portWidth)}</Text>
              {iconWidth ? <Text color={ink.muted}>{padEnd(iconName(project.icon), iconWidth)}</Text> : null}
            </Box>
          )
        })}
      </Box>
    )
  }

  // Details of the selected app: description, then what it is doing.
  const renderDetails = () => {
    if (!selected) return null
    const lines: { text: string; color?: string }[] = []
    const description = selected.description?.trim()
    if (description) lines.push({ text: oneLine(description), color: ink.muted })
    if (phase === 'running') lines.push({ text: selected.url ? t('apps.runningAt', { url: selected.url }) : t('status.running') })
    else if (phase === 'creating') {
      const progress = deriveProgress(todos[selected.id])
      lines.push({
        text: progress.total
          ? t('apps.building', { current: Math.min(progress.total, progress.done + 1), total: progress.total, step: progress.label || t('apps.buildingStep') })
          : t('apps.buildingStart'),
      })
    } else if (phase === 'launching') lines.push({ text: t('apps.launchingHint') })
    else if (phase === 'error' || selected.error) lines.push({ text: selected.error || t('status.error'), color: ink.error })
    const busy = !!selected.sessionId && runState[selected.sessionId] !== undefined
    const extras = [
      busy ? t('apps.agentWorking') : '',
      t('apps.themeLine', { theme: themeName(t, projectThemeId(selected)) }),
      iconName(selected.icon) ? t('apps.iconLine', { icon: iconName(selected.icon) }) : '',
    ].filter(Boolean)
    lines.push({ text: extras.join(' · '), color: ink.muted })
    return lines.slice(0, 3).map((line, i) => (
      <Text key={i} color={line.color}>{truncate(line.text, columns)}</Text>
    ))
  }

  return (
    <Frame title={title} aside={mode.kind === 'list' ? aside : ''} hints={hints} columns={columns} rows={rows}>
      {mode.kind === 'settings' && selected ? (
        <AppSettingsPanel projectId={selected.id} columns={columns} rows={body} active />
      ) : mode.kind === 'theme' && selected ? (
        <ThemePicker
          t={t}
          state={mode.picker}
          currentId={projectThemeId(selected)}
          title={t('theme.title', { name: selected.name })}
          columns={columns}
          rows={body}
        />
      ) : (
        <Box flexDirection="column">
          {renderList()}
          {apps.length > 0 ? <Text> </Text> : null}
          {renderDetails()}
          {confirm ? (
            <Box>
              <Text color={ink.warn} bold>{truncate(confirm.message, Math.max(10, columns - width(t('hint.confirm')) - 2))}</Text>
              <Text color={ink.muted}>{'  ' + t('hint.confirm')}</Text>
            </Box>
          ) : notice ? (
            <Text color={ink.info}>{truncate(notice, columns)}</Text>
          ) : null}
        </Box>
      )}
    </Frame>
  )
}
