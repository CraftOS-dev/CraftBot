/**
 * The chat on the terminal's main screen.
 *
 * Above: the conversation, written into the terminal's own scrollback once
 * per finished unit (native selection, copy and search work on it). Below:
 * a small live region (the running turn, the pinned question, toasts, the
 * composer, the status line), kept well under the viewport height so the
 * renderer never falls back to clearing the screen.
 *
 * One input handler routes every key: global shortcuts first, then the
 * slash popup, the question box when it has focus, and the composer.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Box, Text, useApp, useInput, usePaste, useStdout, useWindowSize, type Key } from 'ink'
import { useTranslation } from 'react-i18next'
import { useStore } from 'react-redux'
import type { RootState } from '../state/store'
import { useAppDispatch, useAppSelector } from '../state/hooks'
import { armQuit, dismissToast, expireToasts, openScreen, pushToast, toggleTodoPanel } from '../state/tuiSlice'
import { send } from '../state/hooks'
import { onInboundMessage } from '../../../browser/frontend/src/store/socket/socketMiddleware'
import { mentionAt, mentionedFiles, pathSuggestions } from '../input/attachments'
import { describeFile, MAX_ATTACHMENTS, MAX_TOTAL_BYTES } from './intents'
import { clearReplyTarget, getReplyTarget, subscribeReplyTarget } from '../screens/transcriptReply'
import { takeTranscriptDump } from '../screens/TranscriptScreen'
import { selectLastMessageIdBySession } from '../../../browser/frontend/src/store/selectors/messages'
import { clearPendingPrefill, setDraftText } from '../../../browser/frontend/src/store/slices/chatInputSlice'
import { RESOURCES, useResource } from '../../../browser/frontend/src/store/resources'
import { markSeen, sendChat, stopSession } from './intents'
import { choiceKey, useSessionLive } from './sessionLive'
import { latestTodos } from './activity'
import { pendingScrollback, reopenActiveSession } from './transcriptWriter'
import { WorkingBlock, workingBlockHeight } from './WorkingBlock'
import { ChoiceBox, choiceBoxHeight } from './ChoiceBox'
import { StatusLine } from './StatusLine'
import { COMPOSER_CHROME_ROWS, ComposerView, composerTextColumns } from '../input/ComposerView'
import { applyKey, applyPaste, EMPTY_MODEL, modelFromText, submittedText, type ComposerModel } from '../input/composer'
import { history, remember } from '../input/history'
import { suggestions, type Suggestion } from '../input/completion'
import { LEADER_BINDINGS, LEADER_TIMEOUT_MS, LOCAL_COMMANDS } from '../keymap/leader'
import { chip, glyphs, ink } from '../theme/theme'
import { padEnd, truncate, width } from '../text/width'
import { ToastLine } from '../ui/ToastLine'
import { requestQuit, startNewChat } from '../runtime/actions'

const QUIT_WINDOW_MS = 800
const FIRST_RUN_KEY = 'craftbot-terminal-first-message-sent'

/** One row of the popup above the composer: a slash command or an @path. */
interface PopupItem {
  value: string
  label: string
  description: string
  kind: 'slash' | 'path'
  /** Where an @path mention starts (it alone is replaced on accept). */
  start: number
}

export function ChatRoot() {
  const { t } = useTranslation('tui')
  const dispatch = useAppDispatch()
  const store = useStore<RootState>()
  const { write } = useStdout()
  const { exit } = useApp()
  const { columns, rows } = useWindowSize()

  const sessionId = useAppSelector(s => s.tui.activeSessionId)
  const { activity, runState, busy, running, choice, choiceCount, runStart, subagents: subagentRows } = useSessionLive(sessionId)
  const toasts = useAppSelector(s => s.tui.toasts)
  const todoOpen = useAppSelector(s => s.tui.todoPanelOpen)
  const quitArmedAt = useAppSelector(s => s.tui.quitArmedAt)
  const draft = useAppSelector(s => s.chatInput.drafts[sessionId] ?? '')
  const commands = useAppSelector(s => s.commandsSettings.commands)
  const skills = useAppSelector(s => s.skillsSettings.skills)
  const lastMessageId = useAppSelector(s => selectLastMessageIdBySession(s)[sessionId])

  useResource(RESOURCES.commands)
  useResource(RESOURCES.skills)
  // The welcome card names the model.
  useResource(RESOURCES.modelSettings)
  const replyTarget = useSyncExternalStore(subscribeReplyTarget, () => getReplyTarget(sessionId))

  // --- composer state ------------------------------------------------------
  const [model, setModelState] = useState<ComposerModel>(() => modelFromText(draft))
  const modelRef = useRef(model)
  const setModel = useCallback((next: ComposerModel) => {
    modelRef.current = next
    setModelState(next)
  }, [])
  const [popupIndex, setPopupIndex] = useState(0)
  const [popupClosed, setPopupClosed] = useState(false)
  const [questionFocus, setQuestionFocus] = useState(false)
  const [optionIndex, setOptionIndex] = useState(0)
  const leaderAt = useRef<number | null>(null)
  const [leaderArmed, setLeaderArmed] = useState(false)
  // The keys that matter, shown until the first message is sent.
  const [showFirstRun, setShowFirstRun] = useState(() => !localStorage.getItem(FIRST_RUN_KEY))

  // Switching sessions keeps each session's unsent draft.
  const lastSession = useRef(sessionId)
  useEffect(() => {
    if (lastSession.current === sessionId) return
    dispatch(setDraftText({ sessionId: lastSession.current, text: modelRef.current.buffer.text }))
    lastSession.current = sessionId
    setModel(modelFromText(store.getState().chatInput.drafts[sessionId] ?? ''))
    setQuestionFocus(false)
  }, [sessionId, dispatch, setModel, store])

  // --- scrollback ------------------------------------------------------------
  const columnsRef = useRef(columns)
  columnsRef.current = columns
  const flushRef = useRef<() => void>(() => {})
  useEffect(() => {
    let scheduled: NodeJS.Timeout | null = null
    const flush = () => {
      scheduled = null
      const state = store.getState()
      // The transcript's "[" asks for the whole conversation in scrollback;
      // it goes after the session view, which may start by clearing.
      const out = pendingScrollback(state, columnsRef.current, state.connection.connected) + (takeTranscriptDump() ?? '')
      if (out) write(out)
    }
    flushRef.current = flush
    flush()
    const unsubscribe = store.subscribe(() => {
      if (!scheduled) scheduled = setTimeout(flush, 30)
    })
    // While a session's history is still loading, check back.
    const poll = setInterval(flush, 500)
    return () => {
      unsubscribe()
      clearInterval(poll)
      if (scheduled) clearTimeout(scheduled)
    }
  }, [store, write])

  // A width change reflows what the terminal already shows, so the live
  // region's old rows no longer line up with what the renderer erases.
  // Print the open session again from the top (the writer clears the screen
  // and the scrollback first). Ctrl+L does the same.
  const redraw = useCallback(() => {
    reopenActiveSession()
    flushRef.current()
  }, [])
  const firstWidth = useRef(columns)
  useEffect(() => {
    if (columns === firstWidth.current) return
    firstWidth.current = columns
    const timer = setTimeout(redraw, 150)
    return () => clearTimeout(timer)
  }, [columns, redraw])

  // The open session's newest message counts as read.
  useEffect(() => {
    if (lastMessageId) markSeen(sessionId, lastMessageId)
  }, [sessionId, lastMessageId])

  // Toasts expire on their own.
  useEffect(() => {
    if (toasts.length === 0) return
    const timer = setInterval(() => dispatch(expireToasts(Date.now())), 500)
    return () => clearInterval(timer)
  }, [toasts.length, dispatch])

  // --- derived live state ----------------------------------------------------
  const todos = todoOpen ? latestTodos(activity) : null
  const mention = mentionAt(model.buffer.text, model.buffer.cursor)
  const popupItems: PopupItem[] = popupClosed
    ? []
    : mention
      ? pathSuggestions(mention.path).map(p => ({ value: p.value, description: p.isDir ? t('composer.folder') : '', label: p.label, kind: 'path' as const, start: mention.start }))
      : [
          // The backend's commands and skills first; the terminal's own
          // screen commands fill what room is left.
          ...suggestions(model.buffer.text, commands, skills, 6),
          ...suggestions(model.buffer.text, LOCAL_COMMANDS.map(c => ({ name: c.name, description: t(c.label) })), []),
        ]
          .filter((s, i, all) => all.findIndex(o => o.value === s.value) === i)
          .slice(0, 8)
          .map((s: Suggestion) => ({ value: s.value, description: s.description, label: s.value, kind: 'slash' as const, start: 0 }))
  const popupOpen = popupItems.length > 0
  const selectedSuggestion = popupItems[Math.min(popupIndex, popupItems.length - 1)]

  useEffect(() => {
    setPopupIndex(0)
  }, [model.buffer.text])
  useEffect(() => {
    if (!choice) setQuestionFocus(false)
    setOptionIndex(0)
  }, [choice?.messageId])

  // --- actions -----------------------------------------------------------------
  const submit = useCallback(async (raw: string) => {
    const { text, removed } = submittedText({ ...modelRef.current, buffer: { text: raw, cursor: raw.length } })
    const trimmed = text.trim()
    if (!trimmed) return
    remember(trimmed)
    if (showFirstRun) {
      localStorage.setItem(FIRST_RUN_KEY, '1')
      setShowFirstRun(false)
    }
    setModel(EMPTY_MODEL)
    dispatch(setDraftText({ sessionId, text: '' }))
    if (removed > 0) dispatch(pushToast(t('composer.invisibleRemoved', { count: removed }), 'info'))

    const local = trimmed.startsWith('/') ? LOCAL_COMMANDS.find(c => `/${c.name}` === trimmed.split(/\s+/)[0]) : undefined
    if (local) {
      if (local.screen) dispatch(openScreen({ id: local.screen }))
      else if (local.action === 'newChat') startNewChat()
      else if (local.action === 'quit') requestQuit(exit)
      else if (local.action === 'effort') dispatch(openScreen({ id: 'settings', arg: 'effort' }))
      return
    }
    try {
      // Files mentioned as @path go along as attachments, within the
      // browser's limits (10 files, 200 MB in total).
      const files = mentionedFiles(text).map(describeFile)
      if (files.length > MAX_ATTACHMENTS) {
        dispatch(pushToast(t('composer.attachTooMany', { count: MAX_ATTACHMENTS }), 'error'))
        return
      }
      if (files.reduce((sum, f) => sum + f.size, 0) > MAX_TOTAL_BYTES) {
        dispatch(pushToast(t('composer.attachTooLarge'), 'error'))
        return
      }
      if (files.length) dispatch(pushToast(t('composer.attached', { count: files.length }), 'info'))
      // A reply armed in the transcript (key r) goes with this message.
      const reply = getReplyTarget(sessionId)
      await sendChat(text, sessionId, files, reply?.originalContent)
      if (reply) clearReplyTarget()
    } catch (err) {
      dispatch(pushToast(t('composer.sendFailed', { error: String((err as Error).message ?? err) }), 'error'))
    }
  }, [dispatch, sessionId, setModel, t, exit, showFirstRun])

  const runLeader = useCallback((input: string) => {
    const binding = LEADER_BINDINGS.find(b => b.key === input)
    if (!binding) return
    if (binding.screen) dispatch(openScreen({ id: binding.screen }))
    else if (binding.action === 'newChat') startNewChat()
    else if (binding.action === 'effort') dispatch(openScreen({ id: 'settings', arg: 'effort' }))
    else if (binding.action === 'enhance') {
      const draft = modelRef.current.buffer.text.trim()
      if (!draft) {
        dispatch(pushToast(t('composer.enhanceUnavailable'), 'info'))
        return
      }
      enhancing.current = Date.now()
      dispatch(pushToast(t('composer.enhancing'), 'info', 30_000, 'enhance'))
      send('enhance_prompt', { content: draft, sessionId })
    }
  }, [dispatch, t, sessionId])

  // AI Enhance: the improved draft replaces the composer text (30 s budget).
  const enhancing = useRef<number | null>(null)
  useEffect(() => onInboundMessage(msg => {
    if (msg.type !== 'prompt_enhanced' || enhancing.current === null) return
    const late = Date.now() - enhancing.current > 30_000
    enhancing.current = null
    dispatch(dismissToast('enhance'))
    const content = (msg as unknown as { content?: string }).content
    if (late || !content) {
      dispatch(pushToast(t('composer.enhanceFailed'), 'error'))
      return
    }
    setModel(modelFromText(content))
  }), [dispatch, setModel, t])

  // --- keys --------------------------------------------------------------------
  const handleKey = useCallback((input: string, key: Key) => {
    const now = Date.now()

    // Ctrl+X leader: the next key picks a screen.
    if (leaderAt.current !== null) {
      const armed = now - leaderAt.current < LEADER_TIMEOUT_MS
      leaderAt.current = null
      setLeaderArmed(false)
      if (armed) {
        runLeader(input)
        return
      }
    }

    if (key.ctrl && input === 'c') {
      if (modelRef.current.buffer.text) {
        setModel(EMPTY_MODEL)
        return
      }
      if (questionFocus) {
        setQuestionFocus(false)
        return
      }
      if (quitArmedAt && now - quitArmedAt < QUIT_WINDOW_MS) {
        requestQuit(exit)
        return
      }
      dispatch(armQuit(now))
      dispatch(pushToast(t('quit.pressAgain'), 'info', QUIT_WINDOW_MS + 200, 'quit'))
      return
    }
    if (key.ctrl && input === 'd' && !modelRef.current.buffer.text) {
      requestQuit(exit)
      return
    }
    if (key.ctrl && input === 'x') {
      leaderAt.current = now
      setLeaderArmed(true)
      return
    }
    if (key.ctrl && input === 'p') {
      dispatch(openScreen({ id: 'palette' }))
      return
    }
    if (key.ctrl && input === 'o') {
      dispatch(openScreen({ id: 'transcript' }))
      return
    }
    if (key.ctrl && input === 't') {
      dispatch(toggleTodoPanel())
      return
    }
    if (key.ctrl && input === 'n') {
      startNewChat()
      return
    }
    if (key.ctrl && input === 'l') {
      redraw()
      return
    }

    // The slash popup takes Up/Down/Tab/Enter/Esc while it is open.
    if (popupOpen && !questionFocus) {
      if (key.upArrow) {
        setPopupIndex(i => (i - 1 + popupItems.length) % popupItems.length)
        return
      }
      if (key.downArrow) {
        setPopupIndex(i => (i + 1) % popupItems.length)
        return
      }
      if (selectedSuggestion?.kind === 'path' && (key.tab || key.return)) {
        // Replace just the @mention under the caret; a folder keeps completing.
        const buf = modelRef.current.buffer
        const text = buf.text.slice(0, selectedSuggestion.start) + selectedSuggestion.value + buf.text.slice(buf.cursor)
        setModel({ ...modelRef.current, buffer: { text, cursor: selectedSuggestion.start + selectedSuggestion.value.length } })
        return
      }
      if (key.tab || (key.return && selectedSuggestion && selectedSuggestion.value !== modelRef.current.buffer.text)) {
        const value = selectedSuggestion.value + ' '
        setModel(modelFromText(value))
        if (key.return && selectedSuggestion) {
          void submit(selectedSuggestion.value)
        }
        return
      }
      if (key.escape) {
        setPopupClosed(true)
        return
      }
    }

    // The pinned question box, when focused, takes every key.
    if (questionFocus && choice) {
      const result = choiceKey(choice, optionIndex, input, key)
      if (result.kind === 'move') setOptionIndex(result.index)
      else if (result.kind === 'blur' || result.kind === 'done') setQuestionFocus(false)
      return
    }

    if (key.tab && choice && !popupOpen) {
      setQuestionFocus(true)
      return
    }
    if (key.escape && getReplyTarget(sessionId)) {
      clearReplyTarget()
      return
    }
    if (key.escape) {
      if (busy && runState !== 'stopping') stopSession(sessionId)
      return
    }
    if (input === '?' && !modelRef.current.buffer.text) {
      dispatch(openScreen({ id: 'help' }))
      return
    }

    const result = applyKey(modelRef.current, input, key, { columns: composerTextColumns(columns), history: history() })
    if (!result.handled) return
    if (result.model !== modelRef.current) {
      setModel(result.model)
      setPopupClosed(false)
    }
    if (result.effect?.kind === 'submit') void submit(result.effect.text)
  }, [busy, choice, columns, dispatch, exit, optionIndex, popupItems, popupOpen, questionFocus, quitArmedAt, redraw, runLeader, runState, selectedSuggestion, sessionId, setModel, submit, t])

  useInput(handleKey)
  usePaste(text => {
    setModel(applyPaste(modelRef.current, text))
  })

  // Text dropped into the composer from elsewhere (the palette's commands).
  const prefill = useAppSelector(s => s.chatInput.pendingPrefill)
  useEffect(() => {
    if (prefill === null) return
    setModel(modelFromText(prefill))
    dispatch(clearPendingPrefill())
  }, [prefill, dispatch, setModel])

  // Persist the draft as it changes, so a crash or a screen switch keeps it.
  useEffect(() => {
    const timer = setTimeout(() => dispatch(setDraftText({ sessionId, text: model.buffer.text })), 300)
    return () => clearTimeout(timer)
  }, [model.buffer.text, sessionId, dispatch])

  // --- layout --------------------------------------------------------------------
  // Top to bottom: the working block, the to-do list, the pinned question,
  // toasts (or the slash popup while it is open), the composer rule and
  // text, the footer. The popup sits above the rule, so the composer never
  // moves. The region stays well under the viewport: the composer gets what
  // the rest leaves of this budget, between one and six rows.
  const g = glyphs()
  const budget = Math.max(10, Math.min(22, Math.floor(rows * 0.5)))
  const choiceBody = Math.max(2, Math.min(8, rows - 16))
  const workingRows = busy ? workingBlockHeight(running?.items ?? [], subagentRows.length) : 0
  const choiceRows = choice ? choiceBoxHeight(choice, columns, choiceBody) : 0
  const todoRows = todos ? Math.min(6, todos.length + 1) : 0
  const toastRows = popupOpen ? 0 : toasts.length
  const firstRunRows = showFirstRun && !popupOpen ? 1 : 0
  const replyRows = replyTarget ? 1 : 0
  const popupRows = popupOpen ? popupItems.length : 0
  const above = 1 + workingRows + todoRows + choiceRows + toastRows + popupRows + firstRunRows + replyRows
  const composerRows = Math.max(1, Math.min(6, budget - above - 1 - COMPOSER_CHROME_ROWS))
  const quitHint = quitArmedAt !== null && Date.now() - quitArmedAt < QUIT_WINDOW_MS
  const labelWidth = Math.min(26, Math.max(10, ...popupItems.map(item => width(item.label))) + 2)

  return (
    <Box flexDirection="column" width={columns} paddingTop={1}>
      {busy ? (
        <WorkingBlock
          startedAt={runStart}
          stopping={runState === 'stopping'}
          waiting={!!choice}
          items={running?.items ?? []}
          subagents={subagentRows}
          columns={columns}
        />
      ) : null}
      {todos ? (
        <Box flexDirection="column">
          <Text>
            <Text color={ink.brand}>{`${g.agent} `}</Text>
            <Text bold>{t('todo.title', { done: todos.filter(x => x.status === 'completed').length, total: todos.length })}</Text>
          </Text>
          {todos.slice(0, 5).map((todo, i, shown) => {
            const done = todo.status === 'completed'
            const active = todo.status === 'in_progress'
            return (
              <Text key={i}>
                <Text color={ink.border}>{`  ${i === shown.length - 1 ? g.last : g.tee} `}</Text>
                <Text color={done ? ink.success : active ? ink.brand : ink.dim}>{done ? g.done : active ? g.running : g.pending} </Text>
                <Text color={done ? ink.muted : undefined} bold={active} strikethrough={done}>
                  {truncate(todo.content, Math.max(4, columns - 8))}
                </Text>
              </Text>
            )
          })}
        </Box>
      ) : null}
      {choice ? (
        <ChoiceBox
          message={choice}
          index={0}
          total={choiceCount}
          focused={questionFocus}
          selected={optionIndex}
          columns={columns}
          maxBodyLines={choiceBody}
        />
      ) : null}
      {popupOpen ? (
        <Box flexDirection="column">
          {popupItems.map((item, i) => {
            const active = i === Math.min(popupIndex, popupItems.length - 1)
            const description = truncate(item.description, Math.max(0, columns - labelWidth - 4))
            return (
              <Text key={item.value + i}>
                <Text color={ink.focus} bold>{active ? `${g.pointer} ` : '  '}</Text>
                <Text color={active ? (chip.bg ? chip.fg : ink.focus) : undefined} backgroundColor={active ? chip.bg : undefined} bold={active}>
                  {padEnd(item.label, labelWidth)}
                </Text>
                <Text color={active && chip.bg ? chip.fg : ink.muted} backgroundColor={active ? chip.bg : undefined}>
                  {active && chip.bg ? padEnd(description, Math.max(0, columns - labelWidth - 3)) : description}
                </Text>
              </Text>
            )
          })}
        </Box>
      ) : (
        toasts.map(toast => <ToastLine key={toast.id} toast={toast} columns={columns} />)
      )}
      {firstRunRows ? <Text color={ink.dim}>{'  ' + truncate(t('firstRun.keys'), columns - 3)}</Text> : null}
      {replyTarget ? (
        <Text>
          <Text color={ink.border}>{`  ${g.vbar} `}</Text>
          <Text color={ink.muted}>
            {truncate(t('composer.replyingTo', { name: replyTarget.displayName.replace(/\s+/g, ' ') }), columns - 5)}
          </Text>
        </Text>
      ) : null}
      <ComposerView
        buffer={model.buffer}
        columns={columns}
        placeholder={t('composer.placeholder')}
        maxRows={composerRows}
        focused={!questionFocus}
        offsetTop={above}
      />
      <StatusLine
        columns={columns}
        hint={leaderArmed ? t('composer.leaderHint') : quitHint ? t('quit.pressAgain') : undefined}
        hintColor={leaderArmed ? ink.brand : quitHint ? ink.warn : undefined}
      />
    </Box>
  )
}
