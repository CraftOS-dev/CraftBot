/**
 * One Agent App in the terminal.
 *
 * Its screens come from the app's declared views.json, or are generated from
 * its operations (Home, then one screen per area). Every number on screen is
 * the result of a declared read op, and every action runs a declared op
 * through a form built from the op's typed parameters, so what the person
 * does and what the agent can do are the same verbs. Destructive ops always
 * ask first. The screen follows the app's live changes and refreshes itself.
 *
 *   Tab / [ ]   screens          j/k   rows          Enter  row detail
 *   letters     the screen's actions (shown in the footer)
 *   :           every op         r     refresh       c      chat with your AI agent
 *   l / s       launch / stop    o     records (read-only)
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppSelector, send } from '../../state/hooks'
import { useScreen, useScreenKeys } from '../context'
import { Frame } from '../../ui/Frame'
import { glyphs, ink, viewMarks } from '../../theme/theme'
import { padEnd, truncate, width as cells } from '../../text/width'
import * as TB from '../../input/TextBuffer'
import { TextField, fieldKey } from '../../ui/TextField'
import {
  renderBlock,
  requiredParams,
  opLabel,
  type Action,
  type Block,
  type Describe,
  type Line,
  type Operation,
  type Screen,
} from '../../../../../../agent-app/view/src/index.ts'
import { describe, followChanges, listRecords, loadApp, prefillFromRow, runOp, type LoadedApp } from '../../apps/engine'
import { formKey, formParams, initForm, type FormState } from '../../apps/opForm'
import { ViewLines } from '../../apps/ViewLines'
import { ChatPane, type ChatPaneKeys } from '../../chat/ChatPane'
import { BuildView } from './BuildView'
import { AppSettingsPanel, useAppSettingsKeys } from './AppSettingsPanel'

type SystemTab = 'ops' | 'records' | 'requests' | 'settings'
type Mode =
  | { kind: 'view' }
  | { kind: 'form'; form: FormState }
  | { kind: 'confirm'; form: FormState }
  | { kind: 'running'; label: string }
  | { kind: 'result'; label: string; data: unknown; error?: string }
  | { kind: 'row'; row: Record<string, unknown>; actions: Action[] }

interface Loaded {
  data: Record<string, unknown>
  errors: Record<string, string>
  loading: boolean
  at: number
}

const sourceKey = (op: string, params?: Record<string, unknown>) => `${op}?${JSON.stringify(params ?? {})}`

function statusGlyph(status: string): string {
  const g = glyphs()
  if (status === 'running' || status === 'ready') return g.unread
  if (status === 'creating' || status === 'launching' || status === 'stopping') return g.running
  if (status === 'error') return g.failed
  return g.idle
}

export function AppScreen({ arg }: { arg?: string }) {
  const { t } = useTranslation('appsView')
  const { columns, rows, setTextFocus } = useScreen()
  const project = useAppSelector(s => s.agentApp.projects.find(p => p.id === arg))
  const busy = useAppSelector(s => (project?.sessionId ? s.agent.runStateBySession[project.sessionId] !== undefined : false))

  const [app, setApp] = useState<LoadedApp | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [tab, setTab] = useState(0)
  const [mode, setMode] = useState<Mode>({ kind: 'view' })
  const [loaded, setLoaded] = useState<Loaded>({ data: {}, errors: {}, loading: false, at: 0 })
  const [blockIndex, setBlockIndex] = useState(0)
  const [rowIndex, setRowIndex] = useState(0)
  const [palette, setPalette] = useState<{ query: TB.Buffer; index: number } | null>(null)
  const [described, setDescribed] = useState<Describe | null>(null)
  const [recordEntity, setRecordEntity] = useState<{ name: string; items: Record<string, unknown>[]; total: number } | null>(null)
  const [chatOpen, setChatOpen] = useState(false)
  const chatKeys = useRef<ChatPaneKeys | null>(null)

  const running = project?.status === 'running' || project?.status === 'ready'

  // Load operations and views from the project folder.
  useEffect(() => {
    if (!project?.path) return
    try {
      setApp(loadApp(project.path))
      setLoadError(null)
    } catch (err) {
      setLoadError(String((err as Error).message ?? err))
    }
  }, [project?.path, project?.status])

  const screens: Screen[] = app?.views.screens ?? []
  const systemTabs: SystemTab[] = ['ops', 'records', 'requests', 'settings']
  const tabCount = screens.length + systemTabs.length
  const screen: Screen | undefined = tab < screens.length ? screens[tab] : undefined
  const systemTab: SystemTab | undefined = tab >= screens.length ? systemTabs[tab - screens.length] : undefined
  const opsByName = useMemo(() => new Map((app?.ops ?? []).map(op => [op.name, op])), [app])

  // Fetch the data the visible screen needs.
  const fetchScreen = useCallback(async () => {
    if (!app || !screen || !running) return
    const sources = new Map<string, { op: Operation; params: Record<string, string> }>()
    for (const block of screen.blocks) {
      const ref = block.source ?? screen.source
      if (!ref) continue
      const op = opsByName.get(ref.op)
      if (!op) continue
      const params = Object.fromEntries(Object.entries(ref.params ?? {}).map(([k, v]) => [k, String(v)]))
      if (requiredParams(op).some(p => !(p in params))) continue
      sources.set(sourceKey(ref.op, ref.params), { op, params })
    }
    setLoaded(prev => ({ ...prev, loading: true }))
    const data: Record<string, unknown> = {}
    const errors: Record<string, string> = {}
    await Promise.all(
      [...sources.entries()].map(async ([key, { op, params }]) => {
        try {
          data[key] = await runOp(app.project, op, params)
        } catch (err) {
          errors[key] = String((err as Error).message ?? err)
        }
      }),
    )
    setLoaded({ data, errors, loading: false, at: Date.now() })
  }, [app, screen, running, opsByName])

  useEffect(() => {
    setBlockIndex(0)
    setRowIndex(0)
    void fetchScreen()
  }, [fetchScreen])

  // Follow live changes: refresh the visible screen shortly after any change.
  const refreshTimer = useRef<NodeJS.Timeout | null>(null)
  useEffect(() => {
    if (!app || !running) return
    let stop: (() => void) | null = null
    let cancelled = false
    void describe(app.project)
      .then(d => {
        if (cancelled) return
        setDescribed(d)
        const collections = screen?.refreshOn ?? Object.keys(d.entities ?? {})
        if (collections.length === 0) return
        stop = followChanges(app.project, collections, () => {
          if (refreshTimer.current) clearTimeout(refreshTimer.current)
          refreshTimer.current = setTimeout(() => void fetchScreen(), 300)
        })
      })
      .catch(() => {})
    return () => {
      cancelled = true
      stop?.()
      if (refreshTimer.current) clearTimeout(refreshTimer.current)
    }
  }, [app, running, screen, fetchScreen])

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
    const form = initForm(op, prefillFromRow(op, row, explicit))
    if (form.fields.length === 0 && !op.destructive) {
      setMode({ kind: 'form', form })
      return
    }
    setMode({ kind: 'form', form })
  }, [])

  const execute = useCallback(async (form: FormState) => {
    if (!app) return
    const label = form.op.label ?? opLabel(form.op)
    setMode({ kind: 'running', label })
    try {
      const data = await runOp(app.project, form.op, formParams(form))
      setMode({ kind: 'result', label, data })
    } catch (err) {
      setMode({ kind: 'result', label, data: null, error: String((err as Error).message ?? err) })
    }
    void fetchScreen()
  }, [app, fetchScreen])

  const runAction = useCallback((action: Action, row?: Record<string, unknown>) => {
    const op = opsByName.get(action.op)
    if (op) openForm(op, row, action.params)
  }, [opsByName, openForm])

  // --- keys ----------------------------------------------------------------------
  const settingsKeys = useAppSettingsKeys(arg ?? '')

  useEffect(() => {
    setTextFocus(mode.kind === 'form' || palette !== null || chatOpen)
  }, [mode.kind, palette, chatOpen, setTextFocus])

  useScreenKeys((input, key) => {
    // The chat pane, when open, takes typing; Esc with nothing running closes it.
    if (chatOpen) {
      if (chatKeys.current?.(input, key)) return true
      if (key.escape) setChatOpen(false)
      return true
    }

    if (mode.kind === 'form') {
      const result = formKey(mode.form, input, key)
      if (result.cancel) setMode({ kind: 'view' })
      else if (result.submit) {
        if (mode.form.op.destructive) setMode({ kind: 'confirm', form: result.state })
        else void execute(result.state)
      } else setMode({ kind: 'form', form: result.state })
      return true
    }
    if (mode.kind === 'confirm') {
      if (input === 'y' || input === 'Y') void execute(mode.form)
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
      const all = (app?.ops ?? []).filter(op => !op.system)
      const q = palette.query.text.toLowerCase()
      const matches = all.filter(op => !q || op.name.toLowerCase().includes(q) || (op.label ?? '').toLowerCase().includes(q))
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
      return true
    }

    if (key.tab || input === ']') {
      setTab(i => (i + (key.shift ? -1 : 1) + tabCount) % tabCount)
      setRecordEntity(null)
      return true
    }
    if (input === '[') {
      setTab(i => (i - 1 + tabCount) % tabCount)
      setRecordEntity(null)
      return true
    }
    if (input === 'c') {
      setChatOpen(true)
      return true
    }
    if (input === ':') {
      setPalette({ query: TB.EMPTY, index: 0 })
      return true
    }
    if (input === 'r') {
      void fetchScreen()
      return true
    }
    if (input === 'l' && project && !running) {
      send('agent_app_launch', { projectId: project.id })
      return true
    }
    if (input === 's' && project && running) {
      send('agent_app_stop', { projectId: project.id })
      return true
    }
    if (input === 'o') {
      setTab(screens.length + systemTabs.indexOf('records'))
      return true
    }

    // Lists: ops and records tabs.
    if (systemTab === 'ops') {
      const all = (app?.ops ?? []).filter(op => !op.system)
      if (key.upArrow || input === 'k') setRowIndex(i => Math.max(0, i - 1))
      else if (key.downArrow || input === 'j') setRowIndex(i => Math.min(all.length - 1, i + 1))
      else if (key.return && all[rowIndex]) openForm(all[rowIndex] as Operation)
      else return false
      return true
    }
    if (systemTab === 'records' || systemTab === 'requests') {
      const entities = Object.keys(described?.entities ?? {}).filter(e => (systemTab === 'requests' ? e === 'agent_requests' : e !== 'agent_requests'))
      if (key.upArrow || input === 'k') setRowIndex(i => Math.max(0, i - 1))
      else if (key.downArrow || input === 'j') setRowIndex(i => Math.min(entities.length - 1, i + 1))
      else if (key.return || systemTab === 'requests') {
        const name = systemTab === 'requests' ? 'agent_requests' : entities[rowIndex]
        if (name && app) {
          void listRecords(app.project, name).then(r => {
            setRecordEntity({ name, items: r.items, total: r.totalItems })
            setRowIndex(0)
          })
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
        const areaActions = screenActions
        setMode({ kind: 'row', row: selectedRow, actions: [...rowActions, ...areaActions.filter(a => !rowActions.some(r => r.key === a.key))] })
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
  if (!project) {
    return (
      <Frame title={t('title')} hints={[{ keys: 'Esc', label: t('hint.back') }]} columns={columns} rows={rows}>
        <Text color={ink.muted}>{t('notFound')}</Text>
      </Frame>
    )
  }

  const tabLabels = [...screens.map(s => s.title), ...systemTabs.map(st => t(`tabs.${st}`))]
  const tabLine = (() => {
    const parts: { text: string; active: boolean }[] = tabLabels.map((label, i) => ({ text: label, active: i === tab }))
    let out = ''
    const segs: { text: string; active: boolean }[] = []
    for (const p of parts) {
      const text = p.active ? `[${p.text}]` : p.text
      if (cells(out + text) + 2 > columns - 1) {
        segs.push({ text: '...', active: false })
        break
      }
      out += text + '  '
      segs.push({ text, active: p.active })
    }
    return segs
  })()

  const aside = `${t('agent')} ${busy ? g.busy : g.idle} ${busy ? t('agentWorking') : t('agentIdle')}`
  const title = `${project.name}  ${statusGlyph(project.status)} ${t(`status.${project.status}`, { defaultValue: project.status })}${project.port ? ` · :${project.port}` : ''} · ${t('asOwner')}`

  const hints = (() => {
    if (mode.kind === 'form') return [{ keys: 'Enter', label: t('hint.nextOrRun') }, { keys: 'Tab', label: t('hint.nextField') }, { keys: 'Esc', label: t('hint.cancel') }]
    if (mode.kind === 'confirm') return [{ keys: 'y', label: t('hint.confirm') }, { keys: t('hint.anyKey'), label: t('hint.cancel') }]
    if (palette) return [{ keys: 'Enter', label: t('hint.open') }, { keys: 'Esc', label: t('hint.cancel') }]
    if (chatOpen) {
      return [
        { keys: 'Enter', label: t('hint.send') },
        { keys: 'PgUp/PgDn', label: t('tui:hint.scroll') },
        { keys: 'Esc', label: busy ? t('hint.stop') : t('hint.closeChat') },
      ]
    }
    const actionHints = [...rowActions, ...screenActions].slice(0, 6).map(a => ({ keys: a.key, label: truncate(a.label ?? a.op, 18) }))
    return [
      ...actionHints,
      { keys: ':', label: t('hint.allOps') },
      { keys: 'c', label: t('hint.chat') },
      { keys: 'Tab', label: t('hint.screens') },
      ...(running ? [{ keys: 's', label: t('hint.stop') }] : [{ keys: 'l', label: t('hint.launch') }]),
    ]
  })()

  const bodyRows = rows - 6
  const chatRows = sideChat ? bodyRows : Math.floor(bodyRows / 2)
  const body = (() => {
    if (project.status === 'creating') return <BuildView projectId={project.id} columns={bodyWidth} rows={bodyRows} />
    if (loadError) return <Text color={ink.error}>{truncate(loadError, bodyWidth)}</Text>
    if (!app) return <Text color={ink.muted}>{t('loading')}</Text>
    if (mode.kind === 'form' || mode.kind === 'confirm') return <FormView mode={mode} width={bodyWidth} />
    if (mode.kind === 'running') return <Text color={ink.brand}>{`${g.running} ${mode.label}...`}</Text>
    if (mode.kind === 'result') {
      return (
        <Box flexDirection="column">
          <Text bold color={mode.error ? ink.error : ink.success}>
            {mode.error ? `${g.failed} ${mode.label}: ${mode.error}` : `${g.done} ${mode.label}`}
          </Text>
          {!mode.error && mode.data !== null ? <ViewLines lines={renderBlock({ type: 'auto' }, mode.data, { width: bodyWidth - 1, maxRows: bodyRows - 4, marks: viewMarks() }).lines.slice(0, bodyRows - 3)} /> : null}
          <Text color={ink.muted}>{t('hint.anyKeyBack')}</Text>
        </Box>
      )
    }
    if (mode.kind === 'row') {
      return (
        <Box flexDirection="column">
          <ViewLines lines={renderBlock({ type: 'keyvalue' }, mode.row, { width: bodyWidth - 1, marks: viewMarks() }).lines.slice(0, bodyRows - 3)} />
          <Text> </Text>
          <Text color={ink.muted}>{mode.actions.map(a => `${a.key} ${a.label ?? a.op}`).join('   ') || t('noActions')}</Text>
        </Box>
      )
    }
    if (palette) {
      const all = (app.ops ?? []).filter(op => !op.system)
      const q = palette.query.text.toLowerCase()
      const matches = all.filter(op => !q || op.name.toLowerCase().includes(q) || (op.label ?? '').toLowerCase().includes(q))
      return (
        <Box flexDirection="column">
          <TextField label=":" buffer={palette.query} focused width={bodyWidth} placeholder={t('paletteHint')} />
          {matches.slice(Math.max(0, palette.index - bodyRows + 3), Math.max(0, palette.index - bodyRows + 3) + bodyRows - 2).map(op => {
            const active = op === matches[palette.index]
            return (
              <Text key={op.name} color={active ? ink.focus : undefined} bold={active}>
                {active ? `${g.pointer} ` : '  '}
                {padEnd(op.name, 28)}
                <Text color={op.destructive ? ink.warn : ink.muted}>{truncate((op.destructive ? `[${t('destructive')}] ` : '') + op.description, Math.max(0, bodyWidth - 32))}</Text>
              </Text>
            )
          })}
        </Box>
      )
    }
    if (systemTab === 'settings') return <AppSettingsPanel projectId={project.id} columns={bodyWidth} rows={bodyRows} active />
    if (!running) return <Text color={ink.muted}>{t('stopped')}</Text>
    if (systemTab === 'ops') {
      const all = (app.ops ?? []).filter(op => !op.system)
      const start = Math.max(0, rowIndex - bodyRows + 2)
      return (
        <Box flexDirection="column">
          {all.slice(start, start + bodyRows - 1).map((op, i) => {
            const active = start + i === rowIndex
            return (
              <Text key={op.name} color={active ? ink.focus : undefined}>
                {active ? `${g.pointer} ` : '  '}
                {padEnd(op.name, 30)}
                <Text color={op.destructive ? ink.warn : ink.muted}>{truncate(op.description, Math.max(0, bodyWidth - 34))}</Text>
              </Text>
            )
          })}
        </Box>
      )
    }
    if (systemTab === 'records' || systemTab === 'requests') {
      if (recordEntity) {
        return (
          <Box flexDirection="column">
            <Text bold color={ink.brand}>{`${recordEntity.name} · ${t('recordCount', { count: recordEntity.total })} · ${t('readOnly')}`}</Text>
            <ViewLines lines={renderBlock({ type: 'auto' }, recordEntity.items, { width: bodyWidth - 1, selected: rowIndex, maxRows: bodyRows - 3, marks: viewMarks() }).lines} />
          </Box>
        )
      }
      const entities = Object.keys(described?.entities ?? {}).filter(e => (systemTab === 'requests' ? e === 'agent_requests' : e !== 'agent_requests'))
      return (
        <Box flexDirection="column">
          <Text color={ink.muted}>{systemTab === 'requests' ? t('requestsHint') : t('recordsHint')}</Text>
          {entities.map((e, i) => (
            <Text key={e} color={i === rowIndex ? ink.focus : undefined}>
              {i === rowIndex ? `${g.pointer} ` : '  '}
              {e}
            </Text>
          ))}
        </Box>
      )
    }
    return (
      <Box flexDirection="column">
        {app.viewsProblems.length ? <Text color={ink.warn}>{truncate(t('viewsInvalid', { problem: app.viewsProblems[0] }), bodyWidth)}</Text> : null}
        {loaded.loading && layout.lines.length === 0 ? <Text color={ink.muted}>{t('loading')}</Text> : null}
        {screen && screen.blocks.length === 0 ? <Text color={ink.muted}>{t('actionsOnly')}</Text> : null}
        <ViewLines lines={layout.lines.slice(0, bodyRows)} />
      </Box>
    )
  })()

  return (
    <Frame title={title} aside={aside} hints={hints} columns={columns} rows={rows}>
      <Box flexDirection="column">
        <Text>
          {tabLine.map((s, i) => (
            <Text key={i} color={s.active ? ink.focus : ink.muted} bold={s.active}>
              {s.text + '  '}
            </Text>
          ))}
        </Text>
        <Box flexDirection={sideChat ? 'row' : 'column'}>
          <Box flexDirection="column" width={bodyWidth} height={chatOpen && !sideChat ? bodyRows - chatRows : bodyRows} overflow="hidden">
            {body}
          </Box>
          {chatOpen && project.sessionId ? (
            <ChatPane
              sessionId={project.sessionId}
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

function FormView({ mode, width }: { mode: Extract<Mode, { kind: 'form' | 'confirm' }>; width: number }) {
  const { t } = useTranslation('appsView')
  const g = glyphs()
  const form = mode.form
  const op = form.op
  return (
    <Box flexDirection="column">
      <Text bold color={op.destructive ? ink.warn : ink.brand}>
        {op.label ?? opLabel(op)}
        <Text color={ink.muted}>{`  ${op.name}`}</Text>
      </Text>
      <Text color={ink.muted}>{truncate(op.description, width)}</Text>
      <Text> </Text>
      {form.fields.length === 0 ? <Text color={ink.muted}>{t('noParams')}</Text> : null}
      {form.fields.map((field, i) => {
        const focused = mode.kind === 'form' && i === form.index
        const label = `${field.param.label ?? field.name}${field.param.required ? '*' : ''}`
        const error = form.errors[field.name]
        const isChoice = field.param.type === 'boolean' || !!field.param.enum?.length
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
            {focused && field.param.description ? <Text color={ink.muted}>{'    ' + truncate(field.param.description, width - 6)}</Text> : null}
          </Box>
        )
      })}
      {mode.kind === 'confirm' ? (
        <Box marginTop={1} flexDirection="column">
          <Text color={ink.warn} bold>{truncate(op.confirm ?? t('confirmDestructive', { label: op.label ?? opLabel(op) }), width)}</Text>
          <Text color={ink.muted}>{t('confirmHint')}</Text>
        </Box>
      ) : null}
    </Box>
  )
}
