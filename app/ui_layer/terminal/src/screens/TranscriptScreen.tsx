/**
 * Transcript (Ctrl+O): the open session in full detail. Every action row
 * (status, name, preview, duration, error text), every reasoning item and
 * every message's details, which the chat's scrollback folds away.
 * Virtualized: only the visible lines render, and each block's lines are
 * built once per width.
 *
 * Keys: arrows or j/k pick a message, PgUp/PgDn page, g/G the ends, Enter
 * folds the picked block, / searches (n/N next and previous match), y copies
 * the picked message as Markdown, r replies to it, [ writes the whole
 * conversation into the terminal's scrollback, v opens it in $EDITOR.
 * Reaching the top loads the next older page of messages.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Box, Text, useApp } from 'ink'
import { useTranslation } from 'react-i18next'
import type { ChatMessage } from '../../../browser/frontend/src/types'
import { useAppDispatch, useAppSelector } from '../state/hooks'
import { closeAllScreens } from '../state/tuiSlice'
import {
  selectSessionHasMoreMessages,
  selectSessionHistoryStatus,
  selectSessionLoadingOlderMessages,
  selectSessionMessages,
} from '../../../browser/frontend/src/store/selectors/messages'
import { selectSessionActivity } from '../../../browser/frontend/src/store/selectors/activity'
import { selectConnected } from '../../../browser/frontend/src/store/selectors/connection'
import { setLoadingOlder } from '../../../browser/frontend/src/store/slices/messagesSlice'
import i18n from '../platform/i18n'
import { Frame, bodyRows, type KeyHint } from '../ui/Frame'
import { TextField, fieldKey } from '../ui/TextField'
import * as TB from '../input/TextBuffer'
import { useScreen, useScreenKeys } from './context'
import { glyphs, ink, tone } from '../theme/theme'
import { truncate, width, wrap } from '../text/width'
import { renderMessage, renderSessionDivider, senderLine } from '../render/transcript'
import { renderMarkdown } from '../render/markdown'
import { isOpenChoice } from '../chat/timeline'
import { requestHistory } from '../chat/intents'
import { sessionTitle } from '../chat/transcriptWriter'
import {
  anchorFor,
  blockAtLine,
  buildBlocks,
  chunkLines,
  chunkMarkdown,
  conversationMarkdown,
  findMatches,
  highlightMatches,
  layoutBlocks,
  maxTop,
  messageMarkdown,
  resolveTop,
  revealBlock,
  slug,
  splitReply,
  stepMatch,
  type Anchor,
  type Block,
  type ChunkLabels,
} from './viewTranscript'
import { copyToClipboard } from './viewClipboard'
import { editorCommand, openInEditor } from './viewEditor'
import { replyTargetFor, setReplyTarget } from './transcriptReply'

// --- "[": the conversation for the terminal's scrollback ---------------------

let scrollbackDump: string | null = null

/**
 * The conversation the user asked to write into the terminal's scrollback
 * (key `[`), taken once: null when nothing is waiting. The screen closes
 * itself after `[`; whoever writes to the main screen next (the runtime
 * before it mounts the chat, or the chat's scrollback writer through Ink's
 * `write`) prints this text first.
 */
export function takeTranscriptDump(): string | null {
  const dump = scrollbackDump
  scrollbackDump = null
  return dump
}

// --- rendering ----------------------------------------------------------------

type T = (key: string, options?: Record<string, unknown>) => string

function chunkLabels(t: T): ChunkLabels {
  return {
    actions: count => i18n.t('tui:transcript.actions', { count }),
    failed: count => i18n.t('tui:transcript.failed', { count }),
    reasoning: t('transcript.reasoning'),
    thinking: t('transcript.thinking'),
    status: {
      running: t('transcript.status.running'),
      waiting: t('transcript.status.waiting'),
      paused: t('transcript.status.paused'),
      pending: t('transcript.status.pending'),
      cancelled: t('transcript.status.cancelled'),
    },
  }
}

function quoteLines(text: string, columns: number, paint: (s: string) => string): string[] {
  const g = glyphs()
  const bar = `${tone.muted(g.vbar)} `
  const out: string[] = []
  for (const line of text.replace(/\t/g, '    ').split('\n')) {
    if (!line.trim()) {
      out.push(tone.muted(g.vbar))
      continue
    }
    for (const piece of wrap(line, Math.max(10, columns - 2))) out.push(bar + paint(piece))
  }
  return out
}

/** A message in full: the chat's rendering, plus the reply quote, an open
 *  question's options and the details payload. */
function messageLines(message: ChatMessage, columns: number, detailsOpen: boolean, t: T): string[] {
  const g = glyphs()
  const { text, quoted } =
    message.style === 'user' ? splitReply(message.content ?? '') : { text: message.content ?? '', quoted: null }
  const lines = [senderLine(message), ...renderMessage({ ...message, content: text, details: undefined }, columns)]
  if (quoted) {
    lines.push(`${tone.muted(g.vbar)} ${tone.muted(t('transcript.replyingTo'))}`)
    for (const line of renderMarkdown(quoted, Math.max(20, columns - 2))) lines.push(`${tone.muted(g.vbar)} ${tone.muted(line)}`)
  }
  if (isOpenChoice(message) && message.options) {
    // renderMessage already lists non-blocking options (requiresChoice false).
    const options = message.requiresChoice === false ? '' : message.options.map((o, i) => `${i + 1} ${o.label}`).join('   ')
    lines.push(tone.warn(`${g.pending} ${t('transcript.waiting')}`) + (options ? `  ${tone.muted(options)}` : ''))
  }
  const details = message.details?.trim()
  if (details) {
    if (detailsOpen) {
      lines.push(tone.muted(`${g.chunk} ${t('transcript.details')}`))
      lines.push(...quoteLines(details, columns, s => s))
    } else {
      lines.push(tone.muted(`${g.chunk} ${t('transcript.detailsHidden', { count: details.split('\n').length })}`))
    }
  }
  return lines
}

function chunkSignature(block: Extract<Block, { kind: 'chunk' }>): string {
  return block.items
    .map(i => `${i.id}:${i.status}:${i.completedAt ?? ''}:${i.error?.length ?? 0}:${i.output?.length ?? 0}:${i.input?.length ?? 0}`)
    .join('|')
}

interface CachedLines {
  signature: unknown
  columns: number
  folded: boolean
  labels: ChunkLabels
  lines: string[]
}

/** Lines of one block, rebuilt only when it, the width or its fold changed. */
function useBlockRenderer(t: T, labels: ChunkLabels) {
  const cache = useRef(new Map<string, CachedLines>())
  return (block: Block, columns: number, folded: boolean): string[] => {
    const signature = block.kind === 'message' ? block.message : chunkSignature(block)
    const hit = cache.current.get(block.key)
    if (hit && hit.signature === signature && hit.columns === columns && hit.folded === folded && hit.labels === labels) {
      return hit.lines
    }
    const lines =
      block.kind === 'message'
        ? messageLines(block.message, columns, !folded, t)
        : chunkLines(block.items, labels, columns, !folded)
    cache.current.set(block.key, { signature, columns, folded, labels, lines })
    return lines
  }
}

function senderHeading(message: ChatMessage, t: T): string {
  const when = new Date(message.timestamp * 1000).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'short' })
  const fallback =
    message.style === 'user'
      ? t('transcript.you')
      : message.style === 'error'
        ? i18n.t('tui:transcript.error')
        : i18n.t('tui:transcript.system')
  return `${message.sender || fallback} · ${when}`
}

/** Hints that fit the footer, dropping the least important first. */
function fitHints(hints: (KeyHint & { priority: number })[], columns: number): KeyHint[] {
  const shown = [...hints]
  const total = () => width(shown.map(h => `${h.keys} ${h.label}`).join('   '))
  while (shown.length > 1 && total() > columns - 1) {
    let lowest = 0
    for (let i = 1; i < shown.length; i++) if (shown[i].priority < shown[lowest].priority) lowest = i
    shown.splice(lowest, 1)
  }
  return shown
}

// --- screen -------------------------------------------------------------------

interface Notice {
  text: string
  tone: 'info' | 'error'
}

export function TranscriptScreen({ arg }: { arg?: string }) {
  const { t } = useTranslation('screensView')
  const tt = t as unknown as T
  const dispatch = useAppDispatch()
  const { suspendTerminal } = useApp()
  const { columns, rows, setTextFocus } = useScreen()
  const activeSession = useAppSelector(s => s.tui.activeSessionId)
  const sessionId = arg || activeSession
  const messages = useAppSelector(s => selectSessionMessages(s, sessionId))
  const activity = useAppSelector(s => selectSessionActivity(s, sessionId))
  const hasMore = useAppSelector(s => selectSessionHasMoreMessages(s, sessionId))
  const loadingOlder = useAppSelector(s => selectSessionLoadingOlderMessages(s, sessionId))
  const historyStatus = useAppSelector(s => selectSessionHistoryStatus(s, sessionId))
  const connected = useAppSelector(selectConnected)
  const title = useAppSelector(s => sessionTitle(s, sessionId))

  const labels = useMemo(() => chunkLabels(tt), [tt])
  const renderBlock = useBlockRenderer(tt, labels)
  const blocks = useMemo(() => buildBlocks(messages, activity), [messages, activity])

  const [folded, setFolded] = useState<ReadonlySet<string>>(new Set())
  const [anchor, setAnchor] = useState<Anchor | null>(null)
  const [selKey, setSelKey] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [query, setQuery] = useState<TB.Buffer>(TB.EMPTY)
  const [searchOrigin, setSearchOrigin] = useState(0)
  const [currentMatch, setCurrentMatch] = useState<number | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)

  const contentWidth = Math.max(20, columns - 2)
  // One row under the list for the search field or a notice.
  const height = Math.max(3, bodyRows(rows) - 1)

  const header = useMemo(() => {
    const g = glyphs()
    if (sessionId !== 'new' && historyStatus !== 'fetched' && messages.length === 0) return [tone.muted(t('transcript.loadingOlder'))]
    if (loadingOlder) return [tone.muted(`${g.running} ${t('transcript.loadingOlder')}`)]
    if (hasMore) return [tone.muted(`${g.chunk} ${t('transcript.olderAbove')}`)]
    if (blocks.length === 0) return [tone.muted(t('transcript.empty'))]
    return [tone.muted(t('transcript.start'))]
  }, [sessionId, historyStatus, messages.length, loadingOlder, hasMore, blocks.length, t])

  const layout = useMemo(
    () => layoutBlocks(blocks, block => renderBlock(block, contentWidth, folded.has(block.key)), contentWidth, header),
    // renderBlock is a fresh closure over a stable cache: these inputs decide the layout.
    [blocks, folded, contentWidth, header, labels],
  )

  const top = resolveTop(anchor, blocks, layout, height)
  const selIndex = (() => {
    if (blocks.length === 0) return -1
    const found = selKey ? blocks.findIndex(b => b.key === selKey) : -1
    return found === -1 ? blocks.length - 1 : found
  })()
  const selected = selIndex >= 0 ? blocks[selIndex] : undefined
  const queryText = query.text.trim()
  const matches = useMemo(() => findMatches(layout.lines, queryText), [layout.lines, queryText])
  const matchSet = useMemo(() => new Set(matches), [matches])

  // The first page of a session nobody opened yet on this connection.
  useEffect(() => {
    if (historyStatus === 'unfetched' && sessionId !== 'new' && connected) requestHistory(sessionId)
  }, [historyStatus, sessionId, connected])

  // Reaching the top loads the next older page (once per oldest message).
  const askedBefore = useRef<number | null>(null)
  const oldest = messages[0]?.timestamp
  useEffect(() => {
    if (top !== 0 || !hasMore || loadingOlder || historyStatus !== 'fetched' || !connected) return
    if (oldest === undefined || askedBefore.current === oldest) return
    askedBefore.current = oldest
    dispatch(setLoadingOlder({ sessionId, loading: true }))
    requestHistory(sessionId, oldest)
  }, [top, hasMore, loadingOlder, historyStatus, connected, oldest, sessionId, dispatch])

  // Notices fade after a few seconds.
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), 4000)
    return () => clearTimeout(timer)
  }, [notice])

  const scrollTo = (next: number) => {
    if (next >= maxTop(layout, height)) setAnchor(null)
    else setAnchor(anchorFor(Math.max(0, next), blocks, layout, height))
  }

  const select = (index: number) => {
    if (index < 0 || index >= blocks.length) return
    setSelKey(index === blocks.length - 1 ? null : blocks[index].key)
    scrollTo(revealBlock(top, index, layout, height))
  }

  const revealLine = (line: number) => {
    const owner = blockAtLine(line, layout)
    if (owner >= 0) setSelKey(owner === blocks.length - 1 ? null : blocks[owner].key)
    if (line < top || line >= top + height) scrollTo(line - Math.floor(height / 3))
  }

  const jumpToMatch = (from: number, dir: 1 | -1, list = matches) => {
    const line = stepMatch(list, from, dir)
    setCurrentMatch(line)
    if (line !== null) revealLine(line)
  }

  const flash = (text: string, tone: Notice['tone'] = 'info') => setNotice({ text, tone })

  const copySelected = () => {
    if (!selected) return
    const text = selected.kind === 'message' ? messageMarkdown(selected.message) : chunkMarkdown(selected.items, labels)
    void copyToClipboard(text)
      .then(how => flash(how === 'system' ? t('transcript.copied') : t('transcript.copiedTerminal')))
      .catch((err: unknown) => flash(t('transcript.copyFailed', { error: String((err as Error)?.message ?? err) }), 'error'))
  }

  const replyToSelected = () => {
    const target = selected?.kind === 'message' ? replyTargetFor(selected.message) : null
    if (!target) {
      const choice = selected?.kind === 'message' && selected.message.style === 'agent' && !!selected.message.options?.length
      flash(choice ? t('transcript.replyChoose') : t('transcript.replyOnlyAgent'))
      return
    }
    setReplyTarget(target)
    dispatch(closeAllScreens())
  }

  const dumpToScrollback = () => {
    const name = t('transcript.title', { session: title })
    let out = renderSessionDivider(name, columns)
    blocks.forEach(block => {
      out += '\n' + (block.kind === 'message' ? messageLines(block.message, columns, true, tt) : chunkLines(block.items, labels, columns)).join('\n') + '\n'
    })
    out += renderSessionDivider(t('transcript.dumpEnd'), columns)
    scrollbackDump = out
    dispatch(closeAllScreens())
  }

  const openEditor = () => {
    const markdown = conversationMarkdown(blocks, {
      title: t('transcript.title', { session: title }),
      heading: m => senderHeading(m, tt),
      labels,
      detailsLabel: t('transcript.details'),
      replyingToLabel: t('transcript.replyingTo'),
    })
    void openInEditor(markdown, slug(title), run => suspendTerminal(run))
      .then(({ path }) => flash(t('transcript.editorSaved', { path })))
      .catch((err: unknown) =>
        flash(
          t('transcript.editorFailed', {
            editor: editorCommand(process.env, process.platform),
            error: String((err as Error)?.message ?? err),
          }),
          'error',
        ),
      )
  }

  const stopSearching = (keep: boolean) => {
    setSearching(false)
    setTextFocus(false)
    if (!keep) {
      setQuery(TB.EMPTY)
      setCurrentMatch(null)
    }
  }

  useScreenKeys((input, key) => {
    if (searching) {
      if (key.escape) {
        stopSearching(false)
        return true
      }
      if (key.return) {
        stopSearching(queryText !== '')
        return true
      }
      const next = fieldKey(query, input, key)
      if (next) {
        setQuery(next)
        const list = findMatches(layout.lines, next.text.trim())
        if (list.length) jumpToMatch(searchOrigin - 1, 1, list)
        else setCurrentMatch(null)
      }
      return true
    }
    if (key.escape && queryText) {
      stopSearching(false)
      return true
    }
    if (key.upArrow || input === 'k') {
      select(Math.max(0, selIndex - 1))
      return true
    }
    if (key.downArrow || input === 'j') {
      select(Math.min(blocks.length - 1, selIndex + 1))
      return true
    }
    if (key.pageUp || (key.ctrl && input === 'u')) {
      const next = Math.max(0, top - (height - 1))
      scrollTo(next)
      const owner = blockAtLine(next, layout)
      if (owner >= 0) setSelKey(owner === blocks.length - 1 ? null : blocks[owner].key)
      return true
    }
    if (key.pageDown || (key.ctrl && input === 'd') || input === ' ') {
      const next = Math.min(maxTop(layout, height), top + (height - 1))
      scrollTo(next)
      const owner = blockAtLine(next, layout)
      if (owner >= 0) setSelKey(owner === blocks.length - 1 ? null : blocks[owner].key)
      return true
    }
    if (key.home || input === 'g') {
      if (blocks.length) setSelKey(blocks.length === 1 ? null : blocks[0].key)
      scrollTo(0)
      return true
    }
    if (key.end || input === 'G') {
      setSelKey(null)
      setAnchor(null)
      return true
    }
    if (key.return) {
      if (!selected) return true
      const canFold = selected.kind === 'chunk' || !!selected.message.details?.trim()
      if (canFold) {
        const next = new Set(folded)
        if (next.has(selected.key)) next.delete(selected.key)
        else next.add(selected.key)
        setFolded(next)
      }
      return true
    }
    if (input === '/') {
      setSearching(true)
      setTextFocus(true)
      setSearchOrigin(top)
      return true
    }
    if ((input === 'n' || input === 'N') && queryText) {
      jumpToMatch(currentMatch ?? top - 1, input === 'n' ? 1 : -1)
      return true
    }
    if (input === 'y') {
      copySelected()
      return true
    }
    if (input === 'r') {
      replyToSelected()
      return true
    }
    if (input === '[') {
      dumpToScrollback()
      return true
    }
    if (input === 'v') {
      openEditor()
      return true
    }
    return false
  })

  const g = glyphs()
  const matchIndex = currentMatch !== null ? matches.indexOf(currentMatch) : -1
  const aside = queryText
    ? matches.length
      ? t('transcript.match', { index: Math.max(1, matchIndex + 1), count: matches.length })
      : t('transcript.noMatch', { query: truncate(queryText, 20) })
    : t('transcript.count', { count: messages.length })

  const hints = fitHints(
    [
      { keys: 'y', label: t('transcript.hint.copy'), priority: 9 },
      { keys: 'r', label: t('transcript.hint.reply'), priority: 8 },
      { keys: '/', label: t('transcript.hint.search'), priority: 10 },
      ...(queryText ? [{ keys: 'n/N', label: t('transcript.hint.match'), priority: 11 }] : []),
      { keys: 'Enter', label: t('transcript.hint.fold'), priority: 4 },
      { keys: '[', label: t('transcript.hint.scrollback'), priority: 6 },
      { keys: 'v', label: t('transcript.hint.editor'), priority: 5 },
      { keys: 'Esc', label: t('transcript.hint.back'), priority: 7 },
    ],
    columns,
  )

  const visible = layout.lines.slice(top, top + height)
  return (
    <Frame title={t('transcript.title', { session: title })} aside={aside} hints={hints} columns={columns} rows={rows}>
      <Box flexDirection="column" height={height}>
        {visible.map((line, i) => {
          const index = top + i
          const owner = layout.blockOf[index]
          const isSelected = owner >= 0 && owner === selIndex
          const isCurrent = index === currentMatch
          const body = queryText && matchSet.has(index) ? highlightMatches(line, queryText) : line
          return (
            <Box key={index} height={1}>
              <Text color={isCurrent ? ink.warn : ink.focus}>{isCurrent ? `${g.pointer} ` : isSelected ? `${g.vbar} ` : '  '}</Text>
              <Text wrap="truncate-end">{body || ' '}</Text>
            </Box>
          )
        })}
      </Box>
      {searching ? (
        <TextField
          label="/"
          buffer={query}
          focused
          width={columns}
          placeholder={`${t('transcript.searchPlaceholder')} · Enter ${t('transcript.hint.keep')} · Esc ${t('transcript.hint.clear')}`}
        />
      ) : notice ? (
        <Text color={notice.tone === 'error' ? ink.error : ink.info} wrap="truncate-end">
          {truncate(notice.text, columns - 1)}
        </Text>
      ) : (
        <Text> </Text>
      )}
    </Frame>
  )
}
