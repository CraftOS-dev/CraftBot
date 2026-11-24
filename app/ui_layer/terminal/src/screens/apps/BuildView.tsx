/**
 * The build view: what an Agent App's build looks like while your AI agent
 * makes it. The terminal version of the browser's ConstructionDock, read
 * only and driven by the same inputs, keyed `framework-build:<sessionId>`:
 *
 *   - `agent_app_build_event` (and the `build_feed` replay on opening): a
 *     paced, coalesced feed with a glyph per kind, each row carrying the
 *     build's picture at that moment (stage, progress, task and file counts);
 *   - `agent_app_todos` (or the session's own copy): the bar before the
 *     first picture arrives.
 *
 * API: <BuildView sessionId name columns rows verifying? asking? /> renders
 * inside the parent's frame body and fills at most `rows` lines of `columns`
 * cells. `asking`: the build waits on a question in its chat.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { AgentAppBuildEvent, BuildSnapshot } from '../../../../browser/frontend/src/types'
import { receiveBuildFeed } from '../../../../browser/frontend/src/store/slices/agentAppSlice'
import { useAppDispatch, useAppSelector } from '../../state/hooks'
import { frameworkRequest } from '../../apps/framework'
import { useTicker } from '../../ui/useTicker'
import { glyphs, ink } from '../../theme/theme'
import { padEnd, truncate, width } from '../../text/width'
import { coalesceEvents, deriveProgress, indeterminateBar, nextPaced, progressBar } from './hostModel'

const NO_EVENTS: AgentAppBuildEvent[] = []
const FEED_MAX = 8

/** Reveal events one at a time so the feed keeps moving instead of jumping. */
function usePacedEvents(events: AgentAppBuildEvent[]): AgentAppBuildEvent[] {
  const [count, setCount] = useState(0)
  useEffect(() => {
    const next = nextPaced(count, events.length)
    if (!next) return
    if (next.delay === 0) {
      setCount(next.count)
      return
    }
    const timer = setTimeout(() => setCount(c => Math.min(c + 1, events.length)), next.delay)
    return () => clearTimeout(timer)
  }, [count, events.length])
  return useMemo(() => events.slice(0, count), [events, count])
}

function kindMark(e: AgentAppBuildEvent, ascii: boolean): { glyph: string; color: string | undefined } {
  const g = glyphs()
  switch (e.kind) {
    case 'test_run':
      return e.tests && e.tests.failed > 0 ? { glyph: g.failed, color: ink.error } : { glyph: g.done, color: ink.success }
    case 'file_write':
      return { glyph: '+', color: ink.brand }
    case 'file_edit':
      return { glyph: '~', color: ink.brand }
    case 'scaffold':
      return { glyph: g.artifact, color: ink.brand }
    case 'read':
      return { glyph: ascii ? '<' : '‹', color: ink.info }
    case 'search':
      return { glyph: '/', color: ink.info }
    case 'run':
      return { glyph: '$', color: ink.muted }
    case 'verify':
      return { glyph: ascii ? 'o' : g.pending, color: ink.info }
    case 'todo':
      return { glyph: g.chunk, color: ink.muted }
    default:
      return { glyph: g.bullet, color: ink.muted }
  }
}

/** Replay the build so far on opening it and after a reconnect; new rows arrive live. */
export function useBuildFeed(sessionId: string | undefined, building: boolean) {
  const dispatch = useAppDispatch()
  const connected = useAppSelector(s => s.connection.connected)
  useEffect(() => {
    if (!building || !sessionId || !connected) return
    let active = true
    frameworkRequest<{ events: AgentAppBuildEvent[]; snapshot: BuildSnapshot | null }>({ operation: 'build_feed', sessionId })
      .then(value => {
        if (active) dispatch(receiveBuildFeed({ projectId: `framework-build:${sessionId}`, ...value }))
      })
      .catch(() => {
        // The live rows still arrive; the replay is best effort.
      })
    return () => {
      active = false
    }
  }, [building, sessionId, connected, dispatch])
}

export function BuildView({ sessionId, name, columns, rows, verifying = false, asking = false }: { sessionId: string; name: string; columns: number; rows: number; verifying?: boolean; asking?: boolean }) {
  const { t } = useTranslation(['appsHost', 'agentapp'])
  const projectId = `framework-build:${sessionId}`
  const sessionTodos = useAppSelector(s => s.sessions.sessions.find(x => x.id === sessionId)?.agentAppBuild?.todos)
  const liveTodos = useAppSelector(s => s.agentApp.todos[projectId])
  const feed = useAppSelector(s => s.agentApp.buildFeeds[projectId])
  const events = feed?.events ?? NO_EVENTS

  const displayed = usePacedEvents(events)
  const todoView = useMemo(() => deriveProgress(liveTodos ?? sessionTodos), [liveTodos, sessionTodos])
  // The bar, status line and counts follow the row being shown.
  const shown = useMemo(() => {
    for (let i = displayed.length - 1; i >= 0; i--) if (displayed[i].snapshot) return displayed[i].snapshot!
    return events.length === 0 ? (feed?.snapshot ?? null) : null
  }, [displayed, events.length, feed?.snapshot])
  // A build only moves forward: never less than the bar has already shown.
  const peak = useRef(0)
  peak.current = Math.max(peak.current, shown ? shown.progress : todoView.indeterminate ? 0 : todoView.progress)
  const known = shown !== null || !todoView.indeterminate
  const tick = useTicker(160, !known)
  const g = glyphs()
  const ascii = g.rule === '-'
  const cols = Math.max(20, columns)

  const launching = shown?.stage === 'launching'
  const title = launching ? t('agentapp:construction.launching', { name }) : t('agentapp:construction.creating', { name })
  const stageLabel = !shown
    ? ''
    : shown.fixing
      ? t('agentapp:construction.fixing')
      : shown.stage === 'building' && shown.task
        ? t('agentapp:construction.stage.buildingTask', { task: shown.task })
        : t(`agentapp:construction.stage.${shown.stage}`)
  const activity = (verifying ? t('appsHost:build.verifying') : asking ? t('agentapp:construction.stage.questions') : '') || stageLabel || todoView.label || t('agentapp:construction.preparingWorkspace')

  const counts = [
    shown?.tasksTotal ? t('agentapp:construction.taskCount', { done: shown.tasksDone, total: shown.tasksTotal }) : '',
    shown?.components ? t('agentapp:construction.componentCount', { count: shown.components }) : '',
    shown?.files ? t('agentapp:construction.fileCount', { count: shown.files }) : '',
  ].filter(Boolean)

  // The bar: cells plus a right-aligned percentage.
  const pct = known ? `${Math.round(peak.current)}%` : ''
  const barCells = Math.max(4, cols - 6)
  const full = g.meterFull
  const empty = ascii ? '-' : g.meterEmpty
  const bar = known ? progressBar(peak.current, barCells, full, empty) : indeterminateBar(tick, barCells, full, empty)

  const header = counts.length > 0 ? 4 : 3
  const feedAll = useMemo(() => coalesceEvents(displayed), [displayed])
  const feedRows = Math.max(0, Math.min(feedAll.length, FEED_MAX, rows - header - 1))
  const rowsShown = feedRows > 0 ? feedAll.slice(-feedRows).reverse() : []

  return (
    <Box flexDirection="column" width={cols}>
      <Text bold color={ink.brand}>{truncate(title, cols)}</Text>
      <Box>
        <Text color={ink.brand}>{bar}</Text>
        <Text color={ink.muted}>{pct ? ' ' + pct.padStart(4) : ''}</Text>
      </Box>
      <Text>{truncate(activity, cols)}</Text>
      {counts.length > 0 ? <Text color={ink.muted}>{truncate(counts.join(` ${g.sep} `), cols)}</Text> : null}
      {feedRows > 0 ? <Text> </Text> : null}
      {rowsShown.map(({ event, count }) => {
        const mark = kindMark(event, ascii)
        const times = count > 1 ? ` ${ascii ? 'x' : '×'}${count}` : ''
        return (
          <Box key={event.id}>
            <Text color={mark.color}>{mark.glyph} </Text>
            <Text>{padEnd(truncate(event.label, Math.max(4, cols - 2 - width(times))), 0)}</Text>
            {times ? <Text color={ink.muted}>{times}</Text> : null}
          </Box>
        )
      })}
    </Box>
  )
}
