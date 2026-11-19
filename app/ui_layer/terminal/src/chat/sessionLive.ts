/**
 * One session's live state, shared by every chat surface (the main chat and
 * the chat pane inside an Agent App screen), so they show the same things the
 * same way: the conversation as units, the running chunk and when the turn
 * started, the question or choice waiting on the user, the sub-agents this
 * session started, the reply being written (what the step is doing, the
 * reply text so far, the actions being prepared), and a message the backend
 * could not accept. Also the keys of the pinned question box and of that
 * rejected message.
 */
import type { Key } from 'ink'
import type { ActionItem, ChatMessage } from '../../../browser/frontend/src/types'
import { useAppSelector } from '../state/hooks'
import { selectPendingQuestions, selectSessionMessages } from '../../../browser/frontend/src/store/selectors/messages'
import { selectSessionActivity } from '../../../browser/frontend/src/store/selectors/activity'
import { selectSessionRunState } from '../../../browser/frontend/src/store/selectors/agent'
import { selectSessionStatus, selectSessionStream } from '../../../browser/frontend/src/store/slices/streamSlice'
import { buildUnits, isOpenChoice, liveChunk, type Unit } from './timeline'
import { answerQuestion, clickOption, dismissQuestion, editSubmission, retrySubmission, type Reference } from './intents'
import type { SubagentRow } from './WorkingBlock'

export function useSessionLive(sessionId: string) {
  const messages = useAppSelector(s => selectSessionMessages(s, sessionId))
  const activity = useAppSelector(s => selectSessionActivity(s, sessionId))
  const runState = useAppSelector(s => selectSessionRunState(s, sessionId))
  const pending = useAppSelector(s => selectPendingQuestions(s, sessionId))
  const subagentLinks = useAppSelector(s => s.tui.subagents)
  const activityBySession = useAppSelector(s => s.activity.bySession)
  const busy = runState !== 'idle'

  const units: Unit[] = buildUnits(messages, activity, busy)
  const running = liveChunk(units)
  const choice: ChatMessage | undefined = pending[0] ?? [...messages].reverse().find(m => !m.isQuestion && isOpenChoice(m))
  const choiceCount = pending.length || (choice ? 1 : 0)
  const runStart = (() => {
    if (!busy) return Date.now()
    const lastUser = [...messages].reverse().find(m => m.style === 'user')
    const first = running?.items[0]?.createdAt
    return Math.min(first ?? Infinity, lastUser ? lastUser.timestamp * 1000 : Infinity, Date.now())
  })()
  const subagents: SubagentRow[] = Object.entries(subagentLinks)
    .filter(([, link]) => link.parentId === sessionId && link.state === 'running')
    .map(([id, link]) => ({
      id,
      agentType: link.agentType,
      actions: (activityBySession[id] ?? []).filter(item => item.itemType === 'action').length,
    }))

  // The reply being written (streamSlice): what the current step is doing,
  // the reply messages until the real ones arrive (same client id), and the
  // actions being prepared until their real rows exist (same ids).
  const stream = useAppSelector(s => selectSessionStream(s, sessionId))
  const stepStatus = useAppSelector(s => selectSessionStatus(s, sessionId))
  const arrived = new Set(messages.map(m => m.clientId).filter(Boolean))
  const drafts: DraftReply[] = (stream?.messages ?? [])
    .filter(m => !arrived.has(m.id) && m.text.trim() !== '')
    .map(m => ({ id: m.id, text: m.text, done: m.done, sender: stream?.sender ?? '', startedAt: stream?.startedAt ?? Date.now() }))
  const recorded = new Set(activity.map(item => item.id))
  const preparing: ActionItem[] = busy
    ? (stream?.actions ?? [])
        .filter(a => !recorded.has(a.id))
        .map(a => ({
          id: a.id,
          name: a.name,
          status: 'pending',
          itemType: 'action',
          sessionId,
          input: a.input,
          displayParam: a.displayParam,
          icon: a.icon,
          integration: a.integration,
        }))
    : []

  // A message the backend could not accept, newest first: it waits above the composer.
  const rejected = [...messages].reverse().find(m => m.style === 'user' && !!m.submissionError)

  return { messages, activity, runState, busy, units, running, choice, choiceCount, runStart, subagents, stepStatus, drafts, preparing, rejected }
}

/** A reply message as it is being written. */
export interface DraftReply {
  id: string
  text: string
  done: boolean
  sender: string
  /** When the reply started (epoch ms). */
  startedAt: number
}

export type ChoiceKeyResult =
  /** Not a key of the box. */
  | { kind: 'none' }
  /** Give focus back to typing. */
  | { kind: 'blur' }
  /** Select another option. */
  | { kind: 'move'; index: number }
  /** Answered or dismissed; focus goes back to typing. */
  | { kind: 'done' }

/**
 * A key while the pinned question box has focus: arrows or digits pick,
 * Enter answers, x dismisses a question (it stops the task), Esc or Tab gives
 * focus back to typing.
 */
export function choiceKey(choice: ChatMessage, selected: number, input: string, key: Key): ChoiceKeyResult {
  const options = choice.options ?? []
  if (key.escape || key.tab) return { kind: 'blur' }
  if (key.leftArrow || key.upArrow) return { kind: 'move', index: Math.max(0, selected - 1) }
  if (key.rightArrow || key.downArrow) return { kind: 'move', index: Math.min(options.length - 1, selected + 1) }
  const digit = Number(input)
  if (Number.isInteger(digit) && digit >= 1 && digit <= options.length) return { kind: 'move', index: digit - 1 }
  if (key.return && options[selected]) {
    const option = options[selected]
    if (choice.isQuestion) answerQuestion(choice, option.value)
    else clickOption(choice, option.value)
    return { kind: 'done' }
  }
  if (input === 'x' && choice.isQuestion) {
    dismissQuestion(choice)
    return { kind: 'done' }
  }
  return { kind: 'none' }
}

export type RejectedKeyResult =
  | { kind: 'none' }
  | { kind: 'blur' }
  /** Sent again; focus goes back to typing. */
  | { kind: 'retried' }
  /** Its text and references go back into the composer. */
  | { kind: 'edit'; text: string; references: Reference[] }

/** A key while the rejected message has focus: r sends it again, e edits it, Esc or Tab leaves. */
export function rejectedKey(message: ChatMessage, input: string, key: Key): RejectedKeyResult {
  if (key.escape || key.tab) return { kind: 'blur' }
  if (input === 'r' && message.clientId) {
    retrySubmission(message.clientId)
    return { kind: 'retried' }
  }
  if (input === 'e' && message.clientId) {
    const taken = editSubmission(message.clientId)
    return taken ? { kind: 'edit', ...taken } : { kind: 'blur' }
  }
  return { kind: 'none' }
}
