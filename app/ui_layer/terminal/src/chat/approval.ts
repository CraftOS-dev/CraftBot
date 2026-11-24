/**
 * The approval prompt's logic, kept pure for tests: which request shows,
 * what the box says (why it asks, the action's inputs), how long is left,
 * and what a key does while the box has focus. The view is ApprovalBox.tsx;
 * the answer goes out with `answerApproval` (intents.ts).
 */
import type { Key } from 'ink'
import type {
  ApprovalDecision,
  ApprovalRequest,
} from '../../../browser/frontend/src/store/slices/securitySlice'
import { formatRemaining } from '../screens/settings/coreLogic'
import { truncate, wrap } from '../text/width'

type Translate = (key: string, options?: Record<string, unknown>) => string

/** The three answers, in the box's order: digit `i + 1` or the letter picks one. */
export const APPROVAL_CHOICES: readonly { decision: ApprovalDecision; letter: string; label: string }[] = [
  { decision: 'allow_once', letter: 'a', label: 'approval.allowOnce' },
  { decision: 'allow_session', letter: 's', label: 'approval.allowSession' },
  { decision: 'deny', letter: 'd', label: 'approval.deny' },
]

/** Most rows the reason takes. */
const REASON_LINES = 2

/**
 * The requests to show, the open chat's first, then oldest first. Ones this
 * client already answered are left out until the backend removes them.
 */
export function approvalQueue(
  approvals: readonly ApprovalRequest[],
  activeSessionId: string,
  answered: readonly string[] = [],
): ApprovalRequest[] {
  return approvals
    .filter(a => !answered.includes(a.id))
    .slice()
    .sort((a, b) => {
      const here = Number(b.session_id === activeSessionId) - Number(a.session_id === activeSessionId)
      return here || a.created_at - b.created_at
    })
}

/** Why it asks, as one sentence. */
export function approvalReason(request: ApprovalRequest, t: Translate, language = 'en'): string {
  if (request.reason === 'untrusted_content') {
    return t('approval.reasonUntrusted', { detail: request.reason_detail || t('approval.outsideContent') })
  }
  const effects = request.effects.map(e => t(`approval.effects.${e}`))
  if (!effects.length) return t('approval.reasonGeneric')
  let list: string
  try {
    list = new Intl.ListFormat(language, { style: 'long', type: 'conjunction' }).format(effects)
  } catch {
    list = effects.join(', ')
  }
  return t('approval.reasonHighRisk', { effects: list })
}

/** One input value as text: strings as they are, anything else as compact JSON. */
function valueText(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === undefined) return ''
  try {
    return JSON.stringify(value) ?? String(value)
  } catch {
    return String(value)
  }
}

/** Tabs and other control characters would break the box's edge. */
function clean(text: string): string {
  return text.replace(/\t/g, '  ').replace(/[\u0000-\u0008\u000B-\u001F\u007F]/g, ' ')
}

/**
 * The action's inputs, one `name: value` per line (a value's further lines
 * continue indented), cut to `columns` cells and at most `maxLines` rows;
 * when more are hidden the last row says how many.
 */
export function inputLines(
  inputs: Record<string, unknown>,
  columns: number,
  maxLines: number,
  more: (count: number) => string,
): string[] {
  const all: string[] = []
  for (const [name, value] of Object.entries(inputs ?? {})) {
    const lines = clean(valueText(value).replace(/\r\n?/g, '\n')).split('\n')
    while (lines.length > 1 && lines[lines.length - 1].trim() === '') lines.pop()
    lines.forEach((line, i) => all.push(i === 0 ? `${name}: ${line}` : `  ${line}`))
  }
  const room = Math.max(4, columns)
  const max = Math.max(1, maxLines)
  if (all.length <= max) return all.map(line => truncate(line, room))
  const shown = all.slice(0, max - 1).map(line => truncate(line, room))
  return [...shown, truncate(more(all.length - shown.length), room)]
}

export interface ApprovalLine {
  text: string
  tone: 'reason' | 'muted' | 'input'
}

/**
 * Everything between the box's edges above its choices: the chat it is in
 * (when not the open one), why it asks, and the inputs.
 */
export function approvalBody(
  request: ApprovalRequest,
  inner: number,
  maxInputLines: number,
  t: Translate,
  options: { language?: string; sessionLabel?: string } = {},
): ApprovalLine[] {
  const lines: ApprovalLine[] = []
  if (options.sessionLabel) lines.push({ text: truncate(t('approval.inSession', { session: options.sessionLabel }), inner), tone: 'muted' })
  const reason = wrap(approvalReason(request, t, options.language), inner).map(l => l.trimEnd())
  const shownReason = reason.length > REASON_LINES ? [...reason.slice(0, REASON_LINES - 1), truncate(reason.slice(REASON_LINES - 1).join(' '), inner)] : reason
  for (const text of shownReason) lines.push({ text, tone: 'reason' })
  const inputs = inputLines(request.inputs, inner, maxInputLines, count => t('approval.moreLines', { count }))
  if (!inputs.length) lines.push({ text: t('approval.noInputs'), tone: 'muted' })
  for (const text of inputs) lines.push({ text, tone: 'input' })
  return lines
}

/** Time left until `expiresAt` (Unix seconds) as m:ss, 0:00 once passed. */
export function approvalTimeLeft(expiresAt: number, nowMs: number): string {
  return formatRemaining(expiresAt * 1000 - nowMs)
}

/** Seconds left until `expiresAt` (never negative). */
export function approvalSecondsLeft(expiresAt: number, nowMs: number): number {
  return Math.max(0, Math.ceil(expiresAt - nowMs / 1000))
}

export type ApprovalKeyResult =
  /** Not a key of the box. */
  | { kind: 'none' }
  /** Give focus back to typing. */
  | { kind: 'blur' }
  /** Select another choice. */
  | { kind: 'move'; index: number }
  /** Send this answer. */
  | { kind: 'answer'; decision: ApprovalDecision }

/**
 * A key while the approval box has focus: digits or arrows pick, Enter
 * answers with the picked choice, a / s / d answer at once, Esc or Tab
 * gives focus back to typing.
 */
export function approvalKey(selected: number, input: string, key: Key): ApprovalKeyResult {
  const last = APPROVAL_CHOICES.length - 1
  if (key.escape || key.tab) return { kind: 'blur' }
  if (key.leftArrow || key.upArrow) return { kind: 'move', index: Math.max(0, selected - 1) }
  if (key.rightArrow || key.downArrow) return { kind: 'move', index: Math.min(last, selected + 1) }
  if (key.return) {
    const choice = APPROVAL_CHOICES[Math.max(0, Math.min(last, selected))]
    return { kind: 'answer', decision: choice.decision }
  }
  if (key.ctrl || key.meta) return { kind: 'none' }
  const digit = Number(input)
  if (input.length === 1 && Number.isInteger(digit) && digit >= 1 && digit <= APPROVAL_CHOICES.length) {
    return { kind: 'move', index: digit - 1 }
  }
  const byLetter = APPROVAL_CHOICES.find(c => c.letter === input.toLowerCase())
  if (byLetter && input.length === 1) return { kind: 'answer', decision: byLetter.decision }
  return { kind: 'none' }
}
