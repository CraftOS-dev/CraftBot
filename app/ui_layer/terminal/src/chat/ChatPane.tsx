/**
 * A chat on one session inside a full-screen screen (an Agent App's chat
 * with your AI agent) that looks and behaves like the main chat: the same
 * blocks under the same gutter marks (one-line action summaries included),
 * the working block while the agent runs, the pinned question box, and the
 * composer with its rule. The newest lines sit at the bottom; PgUp and PgDn
 * scroll back through the conversation.
 *
 *   │ ❯ How much did I spend on food this week?
 *   │
 *   │ ✓ 2 actions · Run op (2) · 1.4s
 *   │
 *   │ ● ¥12,400 across 9 receipts, ¥2,100 under
 *   │   your weekly budget.
 *   │ ⠹ Working… 3.1s · esc stop
 *   │   └ ◐ Run op       expenses.list              1.2s
 *   │ ─────────────────────────────────────────────
 *   │ ❯ Ask your AI agent about this app
 *
 * The host screen routes keys to it through `keysRef` while it has focus;
 * a key the pane does not use (Esc with nothing running) is the host's.
 */
import { useCallback, useEffect, useRef, useState, type MutableRefObject } from 'react'
import { Box, Text, usePaste, type Key } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector } from '../state/hooks'
import { pushToast } from '../state/tuiSlice'
import { selectLastMessageIdBySession, selectSessionHistoryStatus } from '../../../browser/frontend/src/store/selectors/messages'
import { glyphs, ink } from '../theme/theme'
import { truncate } from '../text/width'
import { groupOf, renderUnit, type Group } from '../render/transcript'
import type { Unit } from './timeline'
import { choiceKey, useSessionLive } from './sessionLive'
import { markSeen, requestHistory, sendChat, stopSession } from './intents'
import { WorkingBlock, workingBlockHeight } from './WorkingBlock'
import { ChoiceBox, choiceBoxHeight } from './ChoiceBox'
import { COMPOSER_CHROME_ROWS, ComposerView, composerTextColumns } from '../input/ComposerView'
import { applyKey, applyPaste, EMPTY_MODEL, submittedText, type ComposerModel } from '../input/composer'
import * as TB from '../input/TextBuffer'
import { history, remember } from '../input/history'

export type ChatPaneKeys = (input: string, key: Key) => boolean

export interface ChatPaneProps {
  sessionId: string
  /** Width of the pane, its left rule included. */
  columns: number
  rows: number
  /** Keys arrive (through keysRef) and the caret shows. */
  focused: boolean
  keysRef: MutableRefObject<ChatPaneKeys | null>
  placeholder: string
  emptyText: string
  /** The rule that sets the pane apart: beside the host's content, or above it. */
  divider?: 'left' | 'top'
}

interface Cached {
  signature: unknown
  columns: number
  previous: Group | null
  lines: string[]
}

const printable = (u: Unit) => (u.kind === 'message' ? !u.open : u.final)

function signatureOf(unit: Unit): unknown {
  if (unit.kind === 'message') return unit.message
  return unit.items.map(i => `${i.id}:${i.status}:${i.completedAt ?? ''}:${i.error?.length ?? 0}`).join('|')
}

export function ChatPane({ sessionId, columns, rows: outerRows, focused, keysRef, placeholder, emptyText, divider = 'left' }: ChatPaneProps) {
  const { t } = useTranslation('tui')
  const dispatch = useAppDispatch()
  const g = glyphs()
  const live = useSessionLive(sessionId)
  const { busy, runState, running, choice, choiceCount, runStart, subagents, units } = live
  const historyStatus = useAppSelector(s => selectSessionHistoryStatus(s, sessionId))
  const lastMessageId = useAppSelector(s => selectLastMessageIdBySession(s)[sessionId])
  const inner = Math.max(16, divider === 'left' ? columns - 2 : columns - 1)
  const rows = divider === 'top' ? outerRows - 1 : outerRows

  // This connection may not have loaded the session yet.
  useEffect(() => {
    if (historyStatus === 'unfetched') requestHistory(sessionId)
  }, [historyStatus, sessionId])
  useEffect(() => {
    if (lastMessageId) markSeen(sessionId, lastMessageId)
  }, [sessionId, lastMessageId])

  // --- the conversation as lines, each unit laid out once ---------------------
  const cache = useRef(new Map<string, Cached>())
  const lines: string[] = []
  let previous: Group | null = null
  for (const unit of units) {
    if (!printable(unit)) continue
    const signature = signatureOf(unit)
    const hit = cache.current.get(unit.key)
    let block: string[]
    if (hit && hit.signature === signature && hit.columns === inner && hit.previous === previous) block = hit.lines
    else {
      block = renderUnit(unit, inner, previous).replace(/\n$/, '').split('\n')
      cache.current.set(unit.key, { signature, columns: inner, previous, lines: block })
    }
    // The first block's opening gap is not needed at the top of the pane.
    lines.push(...(lines.length === 0 && block[0] === '' ? block.slice(1) : block))
    previous = groupOf(unit)
  }

  // --- composer ----------------------------------------------------------------
  const [model, setModelState] = useState<ComposerModel>(EMPTY_MODEL)
  const modelRef = useRef(model)
  const setModel = useCallback((next: ComposerModel) => {
    modelRef.current = next
    setModelState(next)
  }, [])
  const [questionFocus, setQuestionFocus] = useState(false)
  const [optionIndex, setOptionIndex] = useState(0)
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    if (!choice) setQuestionFocus(false)
    setOptionIndex(0)
  }, [choice?.messageId])

  // New lines keep a scrolled-back view where it is.
  const lineCount = useRef(lines.length)
  useEffect(() => {
    const grown = lines.length - lineCount.current
    lineCount.current = lines.length
    if (grown > 0) setOffset(o => (o > 0 ? o + grown : 0))
  }, [lines.length])

  const submit = useCallback(async (raw: string) => {
    const { text } = submittedText({ ...modelRef.current, buffer: { text: raw, cursor: raw.length } })
    const trimmed = text.trim()
    if (!trimmed) return
    remember(trimmed)
    setModel(EMPTY_MODEL)
    setOffset(0)
    try {
      await sendChat(text, sessionId)
    } catch (err) {
      dispatch(pushToast(t('composer.sendFailed', { error: String((err as Error).message ?? err) }), 'error'))
    }
  }, [dispatch, sessionId, setModel, t])

  usePaste(text => setModel(applyPaste(modelRef.current, text)), { isActive: focused })

  // --- layout ------------------------------------------------------------------
  const choiceBody = Math.max(2, Math.min(6, rows - 14))
  const workingRows = busy ? workingBlockHeight(running?.items ?? [], subagents.length) : 0
  const choiceRows = choice ? choiceBoxHeight(choice, inner, choiceBody) : 0
  const textRows = Math.max(1, Math.min(4, TB.layout(model.buffer, composerTextColumns(inner)).rows.length))
  // One blank row between the conversation and the live rows, as in the main chat.
  const gapRows = busy || choice ? 1 : 0
  const transcriptRows = Math.max(1, rows - gapRows - workingRows - choiceRows - textRows - COMPOSER_CHROME_ROWS)
  const maxOffset = Math.max(0, lines.length - transcriptRows)
  const shownOffset = Math.min(offset, maxOffset)
  const end = lines.length - shownOffset
  const moreAbove = Math.max(0, end - transcriptRows)
  // The top row says how much is above when the view does not reach the start.
  const visible = moreAbove > 0 ? lines.slice(end - transcriptRows + 1, end) : lines.slice(0, end)
  const page = Math.max(1, transcriptRows - 2)

  keysRef.current = (input, key) => {
    if (questionFocus && choice) {
      const result = choiceKey(choice, optionIndex, input, key)
      if (result.kind === 'move') setOptionIndex(result.index)
      else if (result.kind === 'blur' || result.kind === 'done') setQuestionFocus(false)
      return true
    }
    if (key.pageUp) {
      setOffset(Math.min(maxOffset, shownOffset + page))
      return true
    }
    if (key.pageDown) {
      setOffset(Math.max(0, shownOffset - page))
      return true
    }
    if (key.tab && choice) {
      setQuestionFocus(true)
      return true
    }
    if (key.escape) {
      // Esc stops a running turn, as in the main chat; with nothing running
      // it is the host's (it closes the pane).
      if (busy && runState !== 'stopping') {
        stopSession(sessionId)
        return true
      }
      return false
    }
    const result = applyKey(modelRef.current, input, key, { columns: composerTextColumns(inner), history: history() })
    if (result.model !== modelRef.current) setModel(result.model)
    if (result.effect?.kind === 'submit') void submit(result.effect.text)
    return true
  }

  return (
    <Box
      flexDirection="column"
      width={columns}
      height={outerRows}
      borderStyle="single"
      borderTop={divider === 'top'}
      borderLeft={divider === 'left'}
      borderBottom={false}
      borderRight={false}
      borderColor={ink.border}
      paddingLeft={divider === 'left' ? 1 : 0}
    >
      {/* The newest lines sit at the bottom, right above the live rows. */}
      <Box flexDirection="column" height={transcriptRows} overflow="hidden" justifyContent="flex-end">
        {lines.length === 0 ? (
          <Text color={ink.muted}>{historyStatus === 'fetched' ? emptyText : `${g.ellipsis}`}</Text>
        ) : (
          <>
            {moreAbove > 0 ? <Text color={ink.dim}>{truncate(t('composer.moreAbove', { count: moreAbove + 1 }) + `  PgUp`, inner)}</Text> : null}
            {visible.map((line, i) => (
              // An empty Text takes no row; a space keeps the gap between blocks.
              <Text key={i} wrap="truncate-end">{line || ' '}</Text>
            ))}
          </>
        )}
      </Box>
      {gapRows ? <Text> </Text> : null}
      {busy ? (
        <WorkingBlock
          startedAt={runStart}
          stopping={runState === 'stopping'}
          waiting={!!choice}
          items={running?.items ?? []}
          subagents={subagents}
          columns={inner}
        />
      ) : null}
      {choice ? (
        <ChoiceBox
          message={choice}
          index={0}
          total={choiceCount}
          focused={questionFocus}
          selected={optionIndex}
          columns={inner}
          maxBodyLines={choiceBody}
        />
      ) : null}
      <ComposerView
        buffer={model.buffer}
        columns={inner}
        placeholder={placeholder}
        maxRows={textRows}
        focused={focused && !questionFocus}
        offsetTop={0}
      />
    </Box>
  )
}
