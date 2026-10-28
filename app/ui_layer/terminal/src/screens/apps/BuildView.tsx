/**
 * The build view: what an Agent App's build looks like while your AI agent
 * creates it. The terminal version of the browser's ConstructionDock, read
 * only and driven by the same two inputs:
 *
 *   - `agent_app_todos`: the progress bar, "step N of M" and the current step;
 *   - `agent_app_build_event` (replayed by `agent_app_build_events_replay`):
 *     "built so far" counts, a paced and coalesced feed with a glyph per kind,
 *     and the last lines of the file being written, from the event's snippet.
 *
 * API: <BuildView projectId columns rows /> renders inside the parent's frame
 * body (no Frame of its own) and fills at most `rows` lines of `columns` cells.
 */
import { useEffect, useMemo, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { AgentAppBuildEvent } from '../../../../browser/frontend/src/types'
import { useAppSelector } from '../../state/hooks'
import { useTicker } from '../../ui/useTicker'
import { glyphs, ink } from '../../theme/theme'
import { padEnd, truncate, width } from '../../text/width'
import {
  coalesceEvents,
  deriveProgress,
  indeterminateBar,
  nextPaced,
  progressBar,
  snippetTail,
} from './hostModel'

const NO_EVENTS: AgentAppBuildEvent[] = []
const FEED_MAX = 5
const SNIPPET_MAX = 18
const LINE_REVEAL_MS = 40

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

/** Lines of a new snippet appear quickly one after another, as if being written. */
function useRevealedLines(snippetKey: string, total: number): number {
  const [shown, setShown] = useState(total)
  useEffect(() => {
    setShown(0)
  }, [snippetKey])
  useEffect(() => {
    if (shown >= total) return
    const timer = setTimeout(() => setShown(s => s + 1), LINE_REVEAL_MS)
    return () => clearTimeout(timer)
  }, [shown, total])
  return Math.min(shown, total)
}

interface KindMark {
  glyph: string
  color: string | undefined
}

function kindMark(e: AgentAppBuildEvent, ascii: boolean): KindMark {
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

export function BuildView({ projectId, columns, rows }: { projectId: string; columns: number; rows: number }) {
  const { t } = useTranslation('appsHost')
  const project = useAppSelector(s => s.agentApp.projects.find(p => p.id === projectId))
  const todos = useAppSelector(s => s.agentApp.todos[projectId])
  const events = useAppSelector(s => s.agentApp.buildEvents[projectId]) ?? NO_EVENTS
  const snapshot = useAppSelector(s => s.agentApp.snapshots[projectId])

  const displayed = usePacedEvents(events)
  const view = useMemo(() => deriveProgress(todos), [todos])
  const tick = useTicker(160, view.indeterminate)
  const g = glyphs()
  const ascii = g.rule === '-'
  const cols = Math.max(20, columns)

  const latest = useMemo(() => {
    for (let i = displayed.length - 1; i >= 0; i--) {
      const e = displayed[i]
      if (e.snippet && e.file) return { id: e.id, file: e.file, snippet: e.snippet }
    }
    return null
  }, [displayed])
  const allSnippetLines = useMemo(() => (latest ? snippetTail(latest.snippet, SNIPPET_MAX) : []), [latest])
  const revealed = useRevealedLines(latest?.id ?? '', allSnippetLines.length)

  const name = project?.name ?? projectId
  const launching = !!project && project.status !== 'creating'
  const title = launching ? t('build.launching', { name }) : t('build.creating', { name })
  const step = view.total > 0 ? t('build.step', { current: Math.min(view.total, view.done + 1), total: view.total }) : ''
  const activity = view.label || (launching ? t('build.finalChecks') : t('build.preparing'))

  const counts = [
    snapshot?.collections ? t('build.collections', { count: snapshot.collections }) : '',
    snapshot?.routes ? t('build.routes', { count: snapshot.routes }) : '',
    snapshot?.components ? t('build.components', { count: snapshot.components }) : '',
  ].filter(Boolean)

  // The bar: cells plus a right-aligned percentage.
  const pct = view.indeterminate ? '' : `${Math.round(view.progress)}%`
  const barCells = Math.max(4, cols - 6)
  const full = g.meterFull
  const empty = ascii ? '-' : g.meterEmpty
  const bar = view.indeterminate ? indeterminateBar(tick, barCells, full, empty) : progressBar(view.progress, barCells, full, empty)

  // Budget the rows: header, then the feed, then the code peek.
  const header = counts.length > 0 ? 4 : 3
  let remaining = Math.max(0, rows - header)
  const feedAll = useMemo(() => coalesceEvents(displayed), [displayed])
  const feedAvail = Math.min(feedAll.length, FEED_MAX)
  let feedRows = 0
  if (feedAvail > 0 && remaining >= 2) {
    feedRows = latest ? Math.min(feedAvail, Math.max(1, Math.floor((remaining - 1) / 2))) : Math.min(feedAvail, remaining - 1)
    remaining -= feedRows + 1
  }
  const snippetRows = latest && remaining >= 3 ? Math.min(remaining - 2, SNIPPET_MAX) : 0
  const feed = feedRows > 0 ? feedAll.slice(-feedRows).reverse() : []
  const visibleCode = snippetRows > 0 ? allSnippetLines.slice(0, revealed).slice(-snippetRows) : []

  const titleWidth = Math.max(4, cols - width(step) - 1)
  return (
    <Box flexDirection="column" width={cols}>
      <Box>
        <Text bold color={ink.brand}>{padEnd(truncate(title, titleWidth), titleWidth)}</Text>
        <Text color={ink.muted}>{step ? ' ' + step : ''}</Text>
      </Box>
      <Box>
        <Text color={ink.brand}>{bar}</Text>
        <Text color={ink.muted}>{pct ? ' ' + pct.padStart(4) : ''}</Text>
      </Box>
      <Text>{truncate(activity, cols)}</Text>
      {counts.length > 0 ? (
        <Box>
          <Text color={ink.muted}>{t('build.builtSoFar')} </Text>
          <Text>{truncate(counts.join(' · '), Math.max(4, cols - width(t('build.builtSoFar')) - 1))}</Text>
        </Box>
      ) : null}
      {feedRows > 0 ? <Text> </Text> : null}
      {feed.map(({ event, count }) => {
        const mark = kindMark(event, ascii)
        const times = count > 1 ? ` ${ascii ? 'x' : '×'}${count}` : ''
        return (
          <Box key={event.id}>
            <Text color={mark.color}>{mark.glyph} </Text>
            <Text>{truncate(event.label, Math.max(4, cols - 2 - width(times)))}</Text>
            {times ? <Text color={ink.muted}>{times}</Text> : null}
          </Box>
        )
      })}
      {snippetRows > 0 && latest ? (
        <>
          <Text> </Text>
          <Text color={ink.muted}>{truncate(`${g.rule}${g.rule} ${latest.file} `, cols)}</Text>
          {visibleCode.map((line, i) => (
            <Box key={i}>
              <Text color={ink.muted}>{g.vbar} </Text>
              <Text>{truncate(line, cols - 2)}</Text>
            </Box>
          ))}
        </>
      ) : null}
    </Box>
  )
}
