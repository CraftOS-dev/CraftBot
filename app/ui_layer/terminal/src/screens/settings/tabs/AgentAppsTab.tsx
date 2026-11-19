/**
 * Settings > Agent Apps, as the browser's Settings page shows it
 * (AgentAppSettings, FrameworkSettingsCards): every app of the registry,
 * local and connected, with its status (running, stopped, missing,
 * unavailable, or starting and stopping while that is on its way) and port.
 * The registry's own states show above the list: loading, an error, its
 * stderr notice, and a lost connection (rows then read "last known").
 *
 * Keys: j/k move, Enter (or Right, l) opens the app's settings panel
 * (AppSettingsPanel, the same panel the Apps screen shows), s starts or
 * stops a local app, r asks for a fresh list. In the panel, Esc or Left
 * returns to the list.
 */
import { useEffect, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { useAppDispatch, useAppSelector } from '../../../state/hooks'
import {
  appPhase,
  canChangeState,
  changeAppState,
  frameworkAppKey,
  isTransitional,
  requestAppList,
  type AppPhase,
  type RegistryApp,
} from '../../../apps/framework'
import { AppSettingsPanel, useAppSettingsKeys } from '../../apps/AppSettingsPanel'
import { useTab } from '../tabContext'
import { clampList, listKey, LIST_START } from '../../../ui/list'
import { glyphs, ink } from '../../../theme/theme'
import { truncate } from '../../../text/width'
import { NoticeLine, Row, useConnectKeys, useHints, useNotice, useSpinner } from '../connectKit'

const PHASE_COLOR: Record<AppPhase, string | undefined> = {
  running: ink.success,
  starting: ink.warn,
  stopping: ink.warn,
  stopped: ink.muted,
  missing: ink.warn,
  unreachable: ink.error,
}

export function AgentAppsTab() {
  const { t } = useTranslation('appsSettings')
  const dispatch = useAppDispatch()
  const { active, width, height } = useTab()
  useResource(RESOURCES.agentAppsList)
  const registry = useAppSelector(s => s.agentApp.framework)
  const jobs = useAppSelector(s => s.agentApp.frameworkLifecycle)
  const connected = useAppSelector(s => s.connection.connected)
  const apps = registry.apps as RegistryApp[]

  const [list, setList] = useState(LIST_START)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [notice, showNotice] = useNotice()

  const openApp = openKey ? apps.find(a => frameworkAppKey(a.path, a.id) === openKey) : undefined
  const closePanel = () => setOpenKey(null)
  const panelKeys = useAppSettingsKeys(openApp, closePanel)

  // An app that left the registry (deleted elsewhere) closes its panel.
  useEffect(() => {
    if (openKey && !openApp && registry.hasSnapshot && registry.status === 'success') setOpenKey(null)
  }, [openKey, openApp, registry.hasSnapshot, registry.status])

  const phaseOf = (app: RegistryApp): AppPhase => appPhase(app, jobs[frameworkAppKey(app.path, app.id)])
  const spinner = useSpinner(apps.some(app => isTransitional(phaseOf(app))))
  const stale = !connected || registry.status !== 'success'

  // The registry's state lines, above the list.
  const states: { text: string; color?: string }[] = []
  if (!connected) states.push({ text: t('tab.disconnected'), color: ink.warn })
  else if (registry.status === 'error') states.push({ text: t('tab.failed', { error: registry.error ?? '' }), color: ink.error })
  if (connected && registry.warning) states.push({ text: t('tab.warning', { warning: registry.warning }), color: ink.warn })
  const loading = (registry.status === 'loading' || registry.status === 'idle') && apps.length === 0
  const empty = registry.status === 'success' && apps.length === 0

  const listHeight = Math.max(3, height - 4 - states.length)
  const view = clampList(list, apps.length, listHeight)
  const selected = apps[view.index]

  const startStop = (app: RegistryApp) => {
    const phase = phaseOf(app)
    if (isTransitional(phase)) showNotice(t('lifecycle.busy'), 'warn')
    else if (!canChangeState(app)) showNotice(t('tab.notSupported'), 'warn')
    else if (!connected) showNotice(t('panel.disconnected'), 'warn')
    else if (registry.status !== 'success') showNotice(t('common.listStale'), 'warn')
    else if (!changeAppState(dispatch, app, app.status === 'running' ? 'stop' : 'start')) showNotice(t('lifecycle.notSent'), 'error')
  }

  useConnectKeys((input, key) => {
    if (openKey) {
      if (openApp && panelKeys(input, key)) return true
      if (key.escape || key.leftArrow) {
        setOpenKey(null)
        return true
      }
      return false
    }
    const moved = listKey(view, input, key, apps.length, listHeight)
    if (moved) {
      setList(moved)
      return true
    }
    if (input === 'r') {
      requestAppList()
      showNotice(t('tab.refreshing'))
      return true
    }
    if (!selected) return false
    if (key.return || key.rightArrow || input === 'l') {
      setOpenKey(frameworkAppKey(selected.path, selected.id))
      return true
    }
    if (input === 's') {
      startStop(selected)
      return true
    }
    return false
  })

  useHints(
    openApp
      ? [{ keys: 'Esc', label: t('hint.back') }]
      : [
          { keys: 'Enter', label: t('hint.openApp') },
          { keys: 's', label: t('hint.startStop') },
          { keys: 'r', label: t('hint.reload') },
        ],
  )

  if (openApp) {
    return <AppSettingsPanel app={openApp} columns={width - 1} rows={height} active={active} onDeleted={closePanel} />
  }

  const g = glyphs()
  const running = apps.filter(app => app.status === 'running').length
  const summary = registry.hasSnapshot ? [t('tab.apps', { count: apps.length }), t('tab.running', { count: running })].join(` ${g.sep} `) : ''
  const mark = (phase: AppPhase): string =>
    phase === 'running'
      ? g.unread
      : isTransitional(phase)
        ? spinner || g.running
        : phase === 'missing'
          ? g.warn
          : phase === 'unreachable'
            ? g.failed
            : g.idle

  return (
    <Box flexDirection="column">
      {summary ? <Text color={ink.muted}>{truncate(summary, width - 1)}</Text> : null}
      {states.map((line, i) => (
        <Text key={`state-${i}`} color={line.color}>{truncate(line.text, width - 1)}</Text>
      ))}
      {loading ? <Text color={ink.muted}>{truncate(t('tab.loading'), width - 1)}</Text> : null}
      {empty ? <Text color={ink.muted}>{truncate(t('tab.empty'), width - 1)}</Text> : null}
      {apps.slice(view.top, view.top + listHeight).map((app, i) => {
        const index = view.top + i
        const phase = phaseOf(app)
        const word = t(`status.${phase}`)
        const aside = [
          stale ? t('tab.lastKnown', { status: word }) : word,
          app.connection ? t('tab.connected') : app.port != null ? `:${app.port}` : '',
        ]
          .filter(Boolean)
          .join(' ')
        return (
          <Row
            key={frameworkAppKey(app.path, app.id)}
            selected={active && index === view.index}
            mark={mark(phase)}
            markColor={PHASE_COLOR[phase]}
            label={app.name}
            dim={phase !== 'running'}
            aside={aside}
            width={width}
          />
        )
      })}
      {selected ? (
        <Box marginTop={1}>
          <Text color={ink.muted}>{truncate(selected.connection ? selected.connection.origin : selected.path, width - 1, 'middle')}</Text>
        </Box>
      ) : null}
      <NoticeLine notice={notice} width={width} />
    </Box>
  )
}
