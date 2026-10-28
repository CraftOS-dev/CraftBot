/**
 * One session's live state, shared by every chat surface (the main chat and
 * the chat pane inside an Agent App screen), so they show the same things the
 * same way: the conversation as units, the running chunk and when the turn
 * started, the question or choice waiting on the user, and the sub-agents
 * this session started. Also the keys of the pinned question box.
 */
import type { Key } from 'ink'
import type { ChatMessage } from '../../../browser/frontend/src/types'
import { useAppSelector } from '../state/hooks'
import { selectPendingQuestions, selectSessionMessages } from '../../../browser/frontend/src/store/selectors/messages'
import { selectSessionActivity } from '../../../browser/frontend/src/store/selectors/activity'
import { selectSessionRunState } from '../../../browser/frontend/src/store/selectors/agent'
import { buildUnits, isOpenChoice, liveChunk, type Unit } from './timeline'
import { answerQuestion, clickOption, dismissQuestion } from './intents'
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

  return { messages, activity, runState, busy, units, running, choice, choiceCount, runStart, subagents }
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
