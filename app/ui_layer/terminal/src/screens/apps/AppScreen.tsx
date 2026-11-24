/**
 * One Agent App in the terminal.
 *
 * Its screens are generated from the operations it declares (Home, then one
 * screen per module). Every number on screen is the result of a declared
 * read op, and every action runs a declared op through a form built from the
 * op's typed parameters, so what the person does and what the agent can do
 * are the same verbs. Destructive ops always ask first (the app's own
 * approval step). The visible screen refreshes itself every few seconds.
 *
 * While the app is being built it shows the build instead: its progress, and
 * the builder's questions and requirements review when it stops for you.
 * When the app asks to send requests to your AI agent, a review opens.
 *
 *   Tab / [ ]   screens          j/k   rows          Enter  row detail
 *   letters     the screen's actions (shown in the footer)
 *   :           every op         r     refresh       c      chat with your AI agent
 *   l / s       start / stop     o     records       v      review requests
 *
 * A record opened from Records offers the operations that act on its
 * entity, the record already filled in.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector } from '../../state/hooks'
import { useScreen, useScreenKeys } from '../context'
import { Frame } from '../../ui/Frame'
import { glyphs, ink, viewMarks } from '../../theme/theme'
import { padEnd, truncate, width as cells } from '../../text/width'
import * as TB from '../../input/TextBuffer'
import { TextField, fieldKey } from '../../ui/TextField'
import { frameworkSessionIdentity } from '../../../../browser/frontend/src/features/agentApps/frameworkIdentity'
import { selectPendingQuestions } from '../../../../browser/frontend/src/store/selectors/messages'
import { recordActions, renderBlock, requiredParams, opLabel, type Action, type Block, type Line, type Operation, type Screen } from '../../apps/view'
import { listRecords, listTasks, loadApp, OpError, prefillFromRow, runOp, type LoadedApp } from '../../apps/engine'
import { appPhase, canChangeState, changeAppState, errorText, frameworkAppKey, useAppSession, type RegistryApp } from '../../apps/framework'
import { useAppRequests } from '../../apps/requests'
import { fieldChoices, formKey, formParams, initForm, type FormState } from '../../apps/opForm'
import { ViewLines } from '../../apps/ViewLines'
import { ChatPane, type ChatPaneKeys } from '../../chat/ChatPane'
import { BuildView, useBuildFeed } from './BuildView'
import { BuildCheckpoints, waitingForPerson, type CheckpointKeys } from './BuildCheckpoints'
import { AppSettingsPanel, useAppSettingsKeys } from './AppSettingsPanel'

type SystemTab = 'ops' | 'records' | 'requests' | 'settings'
type Mode =
  | { kind: 'view' }
  | { kind: 'form'; form: FormState }
  | { kind: 'confirm'; form: FormState; approvalKey: string }
  | { kind: 'running'; label: string }
  | { kind: 'result'; label: string; data: unknown; error?: string }
  | { kind: 'row'; row: Record<string, unknown>; actions: Action[] }

interface Loaded {
  data: Record<string, unknown>
  errors: Record<string, string>
  loading: boolean
  at: number
}

const REFRESH_MS = 4000
const sourceKey = (op: string, params?: Record<string, unknown>) => `${op}?${JSON.stringify(params ?? {})}`

export function AppScreen({ arg }: { arg?: string }) {
  const { t } = useTranslation('appsView')
  const dispatch = useAppDispatch()
  const { columns, rows, setTextFocus } = useScreen()

  // A build opened before the registry knows its app keeps showing here: the
  // app is found through the build's conversation once it is registered.
  const pendingSession = arg?.startsWith('pending:') ? arg.slice('pending:'.length) : undefined
  const app = useAppSelector(s => {
    if (!pendingSession) return s.agentApp.framework.apps.find(a => frameworkAppKey(a.path, a.id) === arg) as RegistryApp | undefined
    const identity = frameworkSessionIdentity(s.sessions.sessions.find(x => x.id === pendingSession)?.agentAppFrameworkKey)
    return identity ? (s.agentApp.framework.apps.find(a => a.path === identity.path && a.id === identity.appId) as RegistryApp | undefined) : undefined
  })
  const attached = useAppSession(pendingSession ? undefined : app)
  const sessionId = pendingSession ?? attached.sessionId
  const session = useAppSelector(s => (sessionId ? s.sessions.sessions.find(x => x.id === sessionId) : undefined))
  const job = useAppSelector(s => (app ? s.agentApp.frameworkLifecycle[frameworkAppKey(app.path, app.id)] : undefined))
  const connected = useAppSelector(s => s.connection.connected)
  const busy = useAppSelector(s => (sessionId ? s.agent.runStateBySession[sessionId] !== undefined : false))

  const building = !!session && (!!session.agentAppFrameworkPending || !!session.agentAppBuild?.building)
  const checkpoint = building && waitingForPerson(session?.agentAppBuild?.checkpoint)
  // A build also stops for you with a question in its chat (the importer asks
  // there which route to take): the build view says so and the chat opens on it.
  const question = useAppSelector(s => (sessionId ? selectPendingQuestions(s, sessionId)[0] : undefined))
  const asking = building ? question?.messageId : undefined
  useBuildFeed(sessionId, building)
  const phase = app ? appPhase(app, job) : undefined
  const running = phase === 'running'
  const name = app?.name ?? session?.title ?? t('title')
  const requests = useAppRequests(app?.path, app?.id, running && !app?.connection)

  const [loadedApp, setLoadedApp] = useState<LoadedApp | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [tab, setTab] = useState(0)
  const [mode, setMode] = useState<Mode>({ kind: 'view' })
  const [loaded, setLoaded] = useState<Loaded>({ data: {}, errors: {}, loading: false, at: 0 })
  const [blockIndex, setBlockIndex] = useState(0)
  const [rowIndex, setRowIndex] = useState(0)
  const [palette, setPalette] = useState<{ query: TB.Buffer; index: number } | null>(null)
  const [recordEntity, setRecordEntity] = useState<{ name: string; items: Record<string, unknown>[]; total: number } | null>(null)
  const [tasks, setTasks] = useState<{ items: Record<string, unknown>[]; error?: string } | null>(null)
  const [chatOpen, setChatOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const chatKeys = useRef<ChatPaneKeys | null>(null)
  const checkpointKeys = useRef<CheckpointKeys | null>(null)
  const [checkpointTyping, setCheckpointTyping] = useState(false)

  // Once per question: closing the chat again afterwards is respected.
  useEffect(() => {
    if (asking) setChatOpen(true)
  }, [asking])

  // Connect to the running app and read what it offers.
  const port = app?.port
  useEffect(() => {
    if (!app || !running || building) {
      setLoadedApp(null)
      return
    }
    let active = true
    setLoadError(null)
    loadApp(app)
      .then(value => {
        if (active) setLoadedApp(value)
      })
      .catch(err => {
        if (active) setLoadError(errorText(err))
      })
    return () => {
      active = false
    }
    // The app object changes with every registry snapshot; its identity and port do not.
  }, [app?.path, app?.id, port, running, building])

  const screens: Screen[] = loadedApp?.views.screens ?? []
  const systemTabs: SystemTab[] = app?.connection ? ['ops', 'records', 'settings'] : ['ops', 'records', 'requests', 'settings']
  const tabCount = screens.length + systemTabs.length
  const screen: Screen | undefined = tab < screens.length ? screens[tab] : undefined
  const systemTab: SystemTab | undefined = tab >= screens.length ? systemTabs[tab - screens.length] : undefined
  const opsByName = useMemo(() => new Map((loadedApp?.ops ?? []).map(op => [op.name, op])), [loadedApp])
  const visibleOps = useMemo(() => (loadedApp?.ops ?? []).filter(op => !op.system), [loadedApp])

  // Fetch the data the visible screen needs.
  const fetchScreen = useCallback(async () => {
    if (!loadedApp || !screen) return
    const sources = new Map<string, { op: Operation; params: Record<string, unknown> }>()
    for (const block of screen.blocks) {
      const ref = block.source ?? screen.source
      if (!ref) continue
      const op = opsByName.get(ref.op)
      if (!op) continue
      const params = { ...(ref.params ?? {}) }
      if (requiredParams(op).some(p => !(p in params))) continue
      sources.set(sourceKey(ref.op, ref.params), { op, params })
    }
    setLoaded(prev => ({ ...prev, loading: true }))
    const data: Record<string, unknown> = {}
    const errors: Record<string, string> = {}
    await Promise.all(
      [...sources.entries()].map(async ([key, { op, params }]) => {
        try {
          const outcome = await runOp(loadedApp, op, params)
          data[key] = outcome.kind === 'done' ? outcome.data : null
        } catch (err) {
          errors[key] = errorText(err)
        }
      }),
    )
    setLoaded({ data, errors, loading: false, at: Date.now() })
  }, [loadedApp, screen, opsByName])

  useEffect(() => {
    setBlockIndex(0)
    setRowIndex(0)
    void fetchScreen()
  }, [fetchScreen])

  // Keep the visible screen current while nothing else is open on it.
  const idle = mode.kind === 'view' && !palette
  useEffect(() => {
    if (!screen || !idle) return
    const timer = setInterval(() => void fetchScreen(), REFRESH_MS)
    return () => clearInterval(timer)
  }, [screen, idle, fetchScreen])

  const loadTasks = useCallback(() => {
    if (!loadedApp) return
    listTasks(loadedApp)
      .then(items => setTasks({ items }))
      .catch(err => setTasks({ items: [], error: errorText(err) }))
  }, [loadedApp])
  useEffect(() => {
    if (systemTab === 'requests') loadTasks()
  }, [systemTab, loadTasks])

  // Lay out the visible screen's blocks. The chat sits beside them on a
  // wide terminal and under them on a narrow one.
  const sideChat = columns >= 110
  const chatWidth = sideChat ? Math.min(72, Math.max(46, Math.floor(columns * 0.42))) : columns
  const bodyWidth = chatOpen && sideChat ? columns - chatWidth : columns
  const layout = useMemo(() => {
    if (!screen) return { lines: [] as Line[], selectable: [] as { block: number; rows: Record<string, unknown>[] }[] }
    const lines: Line[] = []
    const selectable: { block: number; rows: Record<string, unknown>[] }[] = []
    screen.blocks.forEach((block: Block, i: number) => {
      const ref = block.source ?? screen.source
      const key = ref ? sourceKey(ref.op, ref.params) : ''
      if (lines.length) lines.push([])
      if (ref && loaded.errors[key]) {
        if (block.title) lines.push([{ text: block.title, tone: 'heading' }])
        lines.push([{ text: `${glyphs().failed} ${loaded.errors[key]}`, tone: 'error' }])
        return
      }
      const isFocused = selectable.length === blockIndex
      const out = renderBlock(block, ref ? loaded.data[key] : undefined, {
        width: bodyWidth - 1,
        selected: isFocused ? rowIndex : -1,
        maxRows: Math.max(4, rows - 12),
        marks: viewMarks(),
      })
      if (out.rows.length) selectable.push({ block: i, rows: out.rows })
      lines.push(...out.lines)
    })
    return { lines, selectable }
  }, [screen, loaded, blockIndex, rowIndex, bodyWidth, rows])

  const focusedRows = layout.selectable[blockIndex]?.rows ?? []
  const selectedRow = focusedRows[rowIndex]
  const screenActions = screen?.actions ?? []
  const focusedBlock = screen?.blocks[layout.selectable[blockIndex]?.block ?? -1]
  const rowActions: Action[] = focusedBlock && (focusedBlock.type === 'table' || focusedBlock.type === 'list') ? focusedBlock.rowActions ?? [] : []

  // --- running ops -------------------------------------------------------------
  const openForm = useCallback((op: Operation, row?: Record<string, unknown>, explicit?: Record<string, string | number | boolean>) => {
    setMode({ kind: 'form', form: initForm(op, prefillFromRow(op, row, explicit)) })
  }, [])

  const execute = useCallback(
    async (form: FormState, approvalKey?: string) => {
      if (!loadedApp) return
      const label = opLabel(form.op)
      let params: Record<string, unknown>
      try {
        params = formParams(form)
      } catch {
        setMode({ kind: 'form', form })
        return
      }
      setMode({ kind: 'running', label })
      try {
        const outcome = await runOp(loadedApp, form.op, params, approvalKey)
        // A destructive op answers with an approval key: the person confirms first.
        if (outcome.kind === 'approval') setMode({ kind: 'confirm', form, approvalKey: outcome.approvalKey })
        else setMode({ kind: 'result', label, data: outcome.data })
      } catch (err) {
        setMode({ kind: 'result', label, data: null, error: err instanceof OpError ? err.message : errorText(err) })
      }
      void fetchScreen()
    },
    [loadedApp, fetchScreen],
  )

  const runAction = useCallback(
    (action: Action, row?: Record<string, unknown>) => {
      const op = opsByName.get(action.op)
      if (op) openForm(op, row, action.params)
    },
    [opsByName, openForm],
  )

  // --- keys ----------------------------------------------------------------------
  const settingsKeys = useAppSettingsKeys(app)
  const reviewing = requests.open

  useEffect(() => {
    setTextFocus(mode.kind === 'form' || palette !== null || chatOpen || checkpointTyping)
  }, [mode.kind, palette, chatOpen, checkpointTyping, setTextFocus])

  const lifecycle = (operation: 'start' | 'stop') => {
    if (!app) return
    if (!connected) setNotice(t('disconnected'))
    else if (!canChangeState(app) || phase === 'starting' || phase === 'stopping') setNotice(t('cannotChange'))
    else changeAppState(dispatch, app, operation)
  }

  useScreenKeys((input, key) => {
    // The request review takes every key until it is answered.
    if (reviewing) {
      if (requests.busy) return true
      if (input === 'y' || input === 'Y') requests.choose(true)
      else if (input === 'n' || input === 'N' || key.escape) requests.close()
      return true
    }
    // The chat pane, when open, takes typing; Esc with nothing running closes it.
    if (chatOpen) {
      if (chatKeys.current?.(input, key)) return true
      if (key.escape) setChatOpen(false)
      return true
    }
    setNotice(null)

    if (building) {
      if (checkpointKeys.current?.(input, key)) return true
      if (input === 'c' && sessionId && !checkpointTyping) {
        setChatOpen(true)
        return true
      }
      return false
    }

    if (mode.kind === 'form') {
      const result = formKey(mode.form, input, key)
      if (result.cancel) setMode({ kind: 'view' })
      else if (result.submit) void execute(result.state)
      else setMode({ kind: 'form', form: result.state })
      return true
    }
    if (mode.kind === 'confirm') {
      if (input === 'y' || input === 'Y') void execute(mode.form, mode.approvalKey)
      else setMode({ kind: 'form', form: mode.form })
      return true
    }
    if (mode.kind === 'running') return true
    if (mode.kind === 'result') {
      setMode({ kind: 'view' })
      return true
    }
    if (mode.kind === 'row') {
      if (key.escape || key.leftArrow || input === 'h') {
        setMode({ kind: 'view' })
        return true
      }
      const action = mode.actions.find(a => a.key === input)
      if (action) runAction(action, mode.row)
      return true
    }

    // The op palette.
    if (palette) {
      const q = palette.query.text.toLowerCase()
      const matches = visibleOps.filter(op => !q || op.name.toLowerCase().includes(q) || (op.description ?? '').toLowerCase().includes(q))
      if (key.escape) {
        setPalette(null)
        return true
      }
      if (key.upArrow || key.downArrow) {
        setPalette({ ...palette, index: Math.max(0, Math.min(matches.length - 1, palette.index + (key.upArrow ? -1 : 1))) })
        return true
      }
      if (key.return) {
        const op = matches[palette.index]
        setPalette(null)
        if (op) openForm(op, selectedRow)
        return true
      }
      const next = fieldKey(palette.query, input, key)
      if (next) setPalette({ query: next, index: 0 })
      return true
    }

    // Settings tab: its panel owns the keys.
    if (systemTab === 'settings' && settingsKeys(input, key)) return true

    // Records drill-down.
    if (systemTab === 'records' && recordEntity) {
      if (key.escape || key.leftArrow || input === 'h') {
        setRecordEntity(null)
        setRowIndex(0)
        return true
      }
      if (key.upArrow || input === 'k') setRowIndex(i => Math.max(0, i - 1))
      else if (key.downArrow || input === 'j') setRowIndex(i => Math.min(recordEntity.items.length - 1, i + 1))
      else if (key.return && recordEntity.items[rowIndex]) {
        setMode({ kind: 'row', row: recordEntity.items[rowIndex], actions: recordActions(visibleOps, recordEntity.name) })
      }
      return true
    }

    if (key.tab || input === ']') {
      setTab(i => (i + (key.shift ? -1 : 1) + tabCount) % Math.max(1, tabCount))
      setRecordEntity(null)
      setRowIndex(0)
      return true
    }
    if (input === '[') {
      setTab(i => (i - 1 + tabCount) % Math.max(1, tabCount))
      setRecordEntity(null)
      setRowIndex(0)
      return true
    }
    if (input === 'c' && sessionId) {
      setChatOpen(true)
      return true
    }
    if (input === 'v' && requests.status && (requests.status.permissionRequired || requests.status.error)) {
      requests.review()
      return true
    }
    if (input === ':' && loadedApp) {
      setPalette({ query: TB.EMPTY, index: 0 })
      return true
    }
    if (input === 'r') {
      if (systemTab === 'requests') loadTasks()
      else void fetchScreen()
      return true
    }
    if (input === 'l' && !running) {
      lifecycle('start')
      return true
    }
    if (input === 's' && running) {
      lifecycle('stop')
      return true
    }
    if (input === 'o' && loadedApp) {
      setTab(screens.length + systemTabs.indexOf('records'))
      setRowIndex(0)
      return true
    }

    // Lists: ops and records tabs.
    if (systemTab === 'ops') {
      if (key.upArrow || input === 'k') setRowIndex(i => Math.max(0, i - 1))
      else if (key.downArrow || input === 'j') setRowIndex(i => Math.min(visibleOps.length - 1, i + 1))
      else if (key.return && visibleOps[rowIndex]) openForm(visibleOps[rowIndex])
      else return false
      return true
    }
    if (systemTab === 'records') {
      const entities = loadedApp?.entities ?? []
      if (key.upArrow || input === 'k') setRowIndex(i => Math.max(0, i - 1))
      else if (key.downArrow || input === 'j') setRowIndex(i => Math.min(entities.length - 1, i + 1))
      else if (key.return) {
        const entity = entities[rowIndex]
        if (entity && loadedApp) {
          listRecords(loadedApp, entity.name)
            .then(r => {
              setRecordEntity({ name: entity.name, items: r.items, total: r.totalItems })
              setRowIndex(0)
            })
            .catch(err => setNotice(errorText(err)))
        }
      } else return false
      return true
    }

    // A screen: rows, row detail and actions.
    if (screen) {
      if (key.upArrow || input === 'k') {
        setRowIndex(i => Math.max(0, i - 1))
        return true
      }
      if (key.downArrow || input === 'j') {
        setRowIndex(i => Math.min(Math.max(0, focusedRows.length - 1), i + 1))
        return true
      }
      if (input === 'n' && layout.selectable.length > 1) {
        setBlockIndex(i => (i + 1) % layout.selectable.length)
        setRowIndex(0)
        return true
      }
      if (key.return && selectedRow) {
        setMode({ kind: 'row', row: selectedRow, actions: [...rowActions, ...screenActions.filter(a => !rowActions.some(r => r.key === a.key))] })
        return true
      }
      const rowAction = rowActions.find(a => a.key === input)
      if (rowAction && selectedRow) {
        runAction(rowAction, selectedRow)
        return true
      }
      const action = screenActions.find(a => a.key === input)
      if (action) {
        runAction(action, selectedRow)
        return true
      }
    }
    return false
  })

  // --- drawing -------------------------------------------------------------------
  const g = glyphs()
  if (!app && !session) {
    return (
      <Frame title={t('title')} hints={[{ keys: 'Esc', label: t('hint.back') }]} columns={columns} rows={rows}>
        <Text color={ink.muted}>{t('notFound')}</Text>
      </Frame>
    )
  }

  const tabLabels = [...screens.map(s => s.title), ...systemTabs.map(st => t(`tabs.${st}`))]
  const tabLine = (() => {
    let out = ''
    const segs: { text: string; active: boolean }[] = []
    for (const [i, label] of tabLabels.entries()) {
      const text = i === tab ? `[${label}]` : label
      if (cells(out + text) + 2 > columns - 1) {
        segs.push({ text: g.ellipsis, active: false })
        break
      }
      out += text + '  '
      segs.push({ text, active: i === tab })
    }
    return segs
  })()

  const statusWord = building ? t('status.building') : phase ? t(`status.${phase}`) : ''
  const statusGlyph = building || phase === 'starting' || phase === 'stopping' ? g.running : running ? g.unread : phase === 'missing' || phase === 'unreachable' ? g.failed : g.idle
  const aside = `${t('agent')} ${busy ? g.busy : g.idle} ${busy ? t('agentWorking') : t('agentIdle')}`
  const title = `${name}  ${statusGlyph} ${statusWord}${app?.port && !app.connection ? ` ${g.sep} :${app.port}` : ''}${app?.connection ? ` ${g.sep} ${t('remote')}` : ` ${g.sep} ${t('asOwner')}`}`

  const hints = (() => {
    if (reviewing) return [{ keys: 'y', label: t('hint.allow') }, { keys: 'n', label: t('hint.decline') }]
    if (chatOpen) {
      return [
        { keys: 'Enter', label: t('hint.send') },
        { keys: 'PgUp/PgDn', label: t('tui:hint.scroll') },
        { keys: 'Esc', label: busy ? t('hint.stop') : t('hint.closeChat') },
      ]
    }
    if (building) return [...(sessionId && !checkpointTyping ? [{ keys: 'c', label: t('hint.chat') }] : []), { keys: 'Esc', label: t('hint.back') }]
    if (mode.kind === 'form') return [{ keys: 'Enter', label: t('hint.nextOrRun') }, { keys: 'Tab', label: t('hint.nextField') }, { keys: 'Esc', label: t('hint.cancel') }]
    if (mode.kind === 'confirm') return [{ keys: 'y', label: t('hint.confirm') }, { keys: t('hint.anyKey'), label: t('hint.cancel') }]
    if (palette) return [{ keys: 'Enter', label: t('hint.open') }, { keys: 'Esc', label: t('hint.cancel') }]
    const actionHints = [...rowActions, ...screenActions].slice(0, 6).map(a => ({ keys: a.key, label: truncate(a.label ?? a.op, 18) }))
    const changeable = app && canChangeState(app) && (phase === 'running' || phase === 'stopped')
    return [
      ...actionHints,
      ...(loadedApp ? [{ keys: ':', label: t('hint.allOps') }] : []),
      ...(sessionId ? [{ keys: 'c', label: t('hint.chat') }] : []),
      { keys: 'Tab', label: t('hint.screens') },
      ...(changeable ? [running ? { keys: 's', label: t('hint.stop') } : { keys: 'l', label: t('hint.launch') }] : []),
    ]
  })()

  // The request banner and notices take a line above the body.
  const banner = (() => {
    if (requests.error) return { text: requests.error, color: ink.error }
    const status = requests.status
    if (status?.needsReview) return { text: `${t(status.changed ? 'requests.pendingChanges' : 'requests.off')}  ${t('requests.reviewKey')}`, color: ink.warn }
    if (status?.error) return { text: `${status.error}  ${t('requests.reviewKey')}`, color: ink.error }
    if (requests.saved === 'allowed') return { text: t(status?.retryNeeded ? 'requests.allowedRetry' : 'requests.allowed'), color: ink.success }
    if (notice) return { text: notice, color: ink.info }
    if (attached.error && !sessionId) return { text: t('chatFailed', { error: attached.error }), color: ink.error }
    return null
  })()

  const bodyRows = rows - 6 - (banner ? 1 : 0)
  const chatRows = sideChat ? bodyRows : Math.floor(bodyRows / 2)
  const contentRows = chatOpen && !sideChat ? bodyRows - chatRows : bodyRows
  const body = (() => {
    if (reviewing) return <RequestReview name={name} requests={requests} width={bodyWidth} />
    if (building && sessionId) {
      return checkpoint ? (
        <BuildCheckpoints sessionId={sessionId} columns={bodyWidth} rows={contentRows} keysRef={checkpointKeys} onTextFocus={setCheckpointTyping} />
      ) : (
        <BuildView sessionId={sessionId} name={name} columns={bodyWidth} rows={contentRows} verifying={!!session?.agentAppBuild?.verifying} asking={!!asking} />
      )
    }
    if (!app) return <Text color={ink.muted}>{t('loading')}</Text>
    if (systemTab === 'settings') return <AppSettingsPanel app={app} columns={bodyWidth} rows={contentRows} active />
    if (!running) {
      if (phase === 'starting' || phase === 'stopping') return <Text color={ink.brand}>{`${g.running} ${t(`status.${phase}`)}${g.ellipsis}`}</Text>
      if (job?.status === 'error') return <Text color={ink.error}>{truncate(job.message || t('lifecycleFailed'), bodyWidth)}</Text>
      return <Text color={ink.muted}>{t(phase === 'missing' ? 'missing' : phase === 'unreachable' ? 'unreachable' : app.connection ? 'remoteOffline' : 'stopped')}</Text>
    }
    if (loadError) return <Text color={ink.error}>{truncate(loadError, bodyWidth)}</Text>
    if (!loadedApp) return <Text color={ink.muted}>{t('loading')}</Text>
    if (mode.kind === 'form' || mode.kind === 'confirm') return <FormView mode={mode} width={bodyWidth} />
    if (mode.kind === 'running') return <Text color={ink.brand}>{`${g.running} ${mode.label}${g.ellipsis}`}</Text>
    if (mode.kind === 'result') {
      return (
        <Box flexDirection="column">
          <Text bold color={mode.error ? ink.error : ink.success}>
            {mode.error ? `${g.failed} ${mode.label}: ${mode.error}` : `${g.done} ${mode.label}`}
          </Text>
          {!mode.error && mode.data !== null ? (
            <ViewLines lines={renderBlock({ type: 'auto' }, mode.data, { width: bodyWidth - 1, maxRows: contentRows - 4, marks: viewMarks() }).lines.slice(0, contentRows - 3)} />
          ) : null}
          <Text color={ink.muted}>{t('hint.anyKeyBack')}</Text>
        </Box>
      )
    }
    if (mode.kind === 'row') {
      return (
        <Box flexDirection="column">
          <ViewLines lines={renderBlock({ type: 'keyvalue' }, mode.row, { width: bodyWidth - 1, marks: viewMarks() }).lines.slice(0, contentRows - 3)} />
          <Text> </Text>
          <Text color={ink.muted}>{mode.actions.map(a => `${a.key} ${a.label ?? a.op}`).join('   ') || t('noActions')}</Text>
        </Box>
      )
    }
    if (palette) {
      const q = palette.query.text.toLowerCase()
      const matches = visibleOps.filter(op => !q || op.name.toLowerCase().includes(q) || (op.description ?? '').toLowerCase().includes(q))
      const start = Math.max(0, palette.index - contentRows + 3)
      return (
        <Box flexDirection="column">
          <TextField label=":" buffer={palette.query} focused width={bodyWidth} placeholder={t('paletteHint')} />
          {matches.slice(start, start + contentRows - 2).map(op => {
            const active = op === matches[palette.index]
            return (
              <Text key={op.name} color={active ? ink.focus : undefined} bold={active}>
                {active ? `${g.pointer} ` : '  '}
                {padEnd(truncate(op.name, 28), 28)}
                <Text color={op.destructive ? ink.warn : ink.muted}>{truncate((op.destructive ? `[${t('destructive')}] ` : '') + (op.description ?? ''), Math.max(0, bodyWidth - 32))}</Text>
              </Text>
            )
          })}
        </Box>
      )
    }
    if (systemTab === 'ops') {
      const start = Math.max(0, rowIndex - contentRows + 2)
      return (
        <Box flexDirection="column">
          {visibleOps.slice(start, start + contentRows - 1).map((op, i) => {
            const active = start + i === rowIndex
            return (
              <Text key={op.name} color={active ? ink.focus : undefined}>
                {active ? `${g.pointer} ` : '  '}
                {padEnd(truncate(op.name, 30), 30)}
                <Text color={op.destructive ? ink.warn : ink.muted}>{truncate(op.description ?? '', Math.max(0, bodyWidth - 34))}</Text>
              </Text>
            )
          })}
        </Box>
      )
    }
    if (systemTab === 'records') {
      if (recordEntity) {
        return (
          <Box flexDirection="column">
            <Text bold color={ink.brand}>{`${recordEntity.name} ${g.sep} ${t('recordCount', { count: recordEntity.total })} ${g.sep} ${t('recordKeys')}`}</Text>
            <ViewLines lines={renderBlock({ type: 'auto' }, recordEntity.items, { width: bodyWidth - 1, selected: rowIndex, maxRows: contentRows - 3, marks: viewMarks() }).lines} />
          </Box>
        )
      }
      const entities = loadedApp.entities
      return (
        <Box flexDirection="column">
          <Text color={ink.muted}>{t('recordsHint')}</Text>
          {entities.length === 0 ? <Text color={ink.muted}>{t('noEntities')}</Text> : null}
          {entities.map((e, i) => (
            <Text key={`${e.module}/${e.name}`} color={i === rowIndex ? ink.focus : undefined}>
              {i === rowIndex ? `${g.pointer} ` : '  '}
              {padEnd(e.name, 28)}
              <Text color={ink.muted}>{e.module}</Text>
            </Text>
          ))}
        </Box>
      )
    }
    if (systemTab === 'requests') {
      const status = requests.status
      const items = tasks?.items ?? []
      return (
        <Box flexDirection="column">
          <Text color={ink.muted}>{t('requestsHint')}</Text>
          <Text color={status?.permissionRequired ? ink.warn : ink.muted}>
            {truncate(
              status === null
                ? t('loading')
                : status.permissionRequired
                  ? t('requests.waitingOff', { count: status.requests?.length ?? 0 })
                  : t('requests.consentOk'),
              bodyWidth,
            )}
          </Text>
          {tasks?.error ? <Text color={ink.error}>{truncate(tasks.error, bodyWidth)}</Text> : null}
          {items.length === 0 && tasks && !tasks.error ? <Text color={ink.muted}>{t('requests.none')}</Text> : null}
          {items.length > 0 ? (
            <ViewLines lines={renderBlock({ type: 'auto' }, items.map(taskRow), { width: bodyWidth - 1, maxRows: contentRows - 3, marks: viewMarks() }).lines} />
          ) : null}
        </Box>
      )
    }
    return (
      <Box flexDirection="column">
        {loaded.loading && layout.lines.length === 0 ? <Text color={ink.muted}>{t('loading')}</Text> : null}
        {screen && screen.blocks.length === 0 ? <Text color={ink.muted}>{t('actionsOnly')}</Text> : null}
        <ViewLines lines={layout.lines.slice(0, contentRows)} />
      </Box>
    )
  })()

  return (
    <Frame title={title} aside={aside} hints={hints} columns={columns} rows={rows}>
      <Box flexDirection="column">
        {banner ? <Text color={banner.color}>{truncate(banner.text, columns)}</Text> : null}
        {!building && loadedApp ? (
          <Text>
            {tabLine.map((s, i) => (
              <Text key={i} color={s.active ? ink.focus : ink.muted} bold={s.active}>
                {s.text + '  '}
              </Text>
            ))}
          </Text>
        ) : null}
        <Box flexDirection={sideChat ? 'row' : 'column'}>
          <Box flexDirection="column" width={bodyWidth} height={contentRows} overflow="hidden">
            {body}
          </Box>
          {chatOpen && sessionId ? (
            <ChatPane
              sessionId={sessionId}
              columns={chatWidth}
              rows={chatRows}
              focused
              keysRef={chatKeys}
              placeholder={t('chatPlaceholder')}
              emptyText={t('chatEmpty')}
              divider={sideChat ? 'left' : 'top'}
            />
          ) : null}
        </Box>
      </Box>
    </Frame>
  )
}

/** One task of the app's queue as a row: what it asks for, its state, when. */
function taskRow(task: Record<string, unknown>): Record<string, unknown> {
  const request = (task.request ?? {}) as { capability?: string }
  return {
    request: request.capability ?? task.event ?? task.id,
    status: task.status,
    created: task.createdAt ?? task.created,
  }
}

function RequestReview({ name, requests, width }: { name: string; requests: ReturnType<typeof useAppRequests>; width: number }) {
  const { t } = useTranslation('appsView')
  const g = glyphs()
  const list = requests.status?.requests ?? []
  return (
    <Box flexDirection="column">
      <Text bold color={ink.warn}>{truncate(t('requests.title'), width)}</Text>
      <Text> </Text>
      {list.length > 0 ? <Text>{truncate(t('requests.intro', { name }), width)}</Text> : null}
      {list.slice(0, 8).map(request => (
        <Text key={request}>{truncate(`  ${g.bullet} ${request.replace(/_/g, ' ')}`, width)}</Text>
      ))}
      {list.length > 8 ? <Text color={ink.muted}>{t('requests.more', { count: list.length - 8 })}</Text> : null}
      <Text> </Text>
      {requests.error ? <Text color={ink.error}>{truncate(requests.error, width)}</Text> : null}
      <Text color={ink.muted}>{requests.busy ? `${g.running} ${t('requests.saving')}` : t('requests.keys')}</Text>
    </Box>
  )
}

function FormView({ mode, width }: { mode: Extract<Mode, { kind: 'form' | 'confirm' }>; width: number }) {
  const { t } = useTranslation('appsView')
  const g = glyphs()
  const form = mode.form
  const op = form.op
  return (
    <Box flexDirection="column">
      <Text bold color={op.destructive ? ink.warn : ink.brand}>
        {opLabel(op)}
        <Text color={ink.muted}>{`  ${op.name}`}</Text>
      </Text>
      {op.description ? <Text color={ink.muted}>{truncate(op.description, width)}</Text> : null}
      <Text> </Text>
      {form.fields.length === 0 ? <Text color={ink.muted}>{t('noParams')}</Text> : null}
      {form.fields.map((field, i) => {
        const focused = mode.kind === 'form' && i === form.index
        const label = `${field.name}${field.param.required ? '*' : ''}`
        const error = form.errors[field.name]
        const isChoice = field.param.type === 'boolean' || fieldChoices(field.param).length > 0
        const hint = field.param.description ?? (field.param.type.startsWith('list<') ? t('listHint') : field.param.type === 'json' ? t('jsonHint') : '')
        return (
          <Box key={field.name} flexDirection="column">
            <Box>
              <Text color={focused ? ink.focus : undefined}>{focused ? `${g.pointer} ` : '  '}</Text>
              {isChoice ? (
                <Text color={focused ? ink.focus : undefined}>
                  {padEnd(label, 22)} {focused ? `< ${field.value.text || '-'} >` : field.value.text || '-'}
                </Text>
              ) : (
                <TextField label={padEnd(label, 22)} buffer={field.value} focused={focused} width={width - 2} />
              )}
              {error ? <Text color={ink.error}>{`  ${t(`fieldError.${error}`)}`}</Text> : null}
            </Box>
            {focused && hint ? <Text color={ink.muted}>{'    ' + truncate(hint, width - 6)}</Text> : null}
          </Box>
        )
      })}
      {mode.kind === 'confirm' ? (
        <Box marginTop={1} flexDirection="column">
          <Text color={ink.warn} bold>{truncate(t('confirmDestructive', { label: opLabel(op) }), width)}</Text>
          <Text color={ink.muted}>{t('confirmHint')}</Text>
        </Box>
      ) : null}
    </Box>
  )
}
