// Pure formatters for the speech-bubble narration. Lifted out of
// useMascotNarration so they're plain functions (easy to reason about,
// easy to test) and so the hook stays focused on the state machine.

import type { ActionItem } from '../../browser/frontend/src/types'

/** Truncate `s` to at most `max` chars, appending an ellipsis on truncation. */
export function trim(s: string, max: number): string {
  return s.length > max ? s.slice(0, max).trimEnd() + '…' : s
}

/** Render any value to a string, capped at `max` chars. Strings pass through;
 *  everything else goes through JSON.stringify. nullish → empty string. */
export function stringifyValue(v: unknown, max = 100): string {
  if (v == null) return ''
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return trim(s, max)
}

/** Pull the most informative single value out of an action's parsed input
 *  for the "Running X with Y" bubble.
 *
 *  - Empty/no dict → empty string.
 *  - One entry → just that value (the param speaks for itself).
 *  - Multiple → the longest string value (heuristic: that's usually the
 *    prompt/query/main argument), falling back to a compact key=value list. */
export function formatParams(input: Record<string, unknown> | null): string {
  if (!input) return ''
  const entries = Object.entries(input)
  if (entries.length === 0) return ''
  if (entries.length === 1) return stringifyValue(entries[0][1])

  let primary: [string, string] | null = null
  for (const [k, v] of entries) {
    if (typeof v === 'string' && (!primary || v.length > primary[1].length)) {
      primary = [k, v]
    }
  }
  if (primary) return stringifyValue(primary[1])

  return trim(entries.map(([k, v]) => `${k}=${stringifyValue(v, 30)}`).join(', '), 140)
}

/** Pull a human-readable result string from an action. Prefers parsed-dict
 *  fields commonly carrying the "main" output (text/content/result/message/
 *  output), then falls back to the raw output string, then to a generic
 *  "Done". Error/cancelled statuses are surfaced explicitly so the bubble
 *  reads as a state change rather than just "Done". */
export function formatResult(item: ActionItem, output: Record<string, unknown> | null): string {
  if (item.status === 'error' || item.error) {
    const err = item.error ?? String(output?.error ?? '')
    return err ? trim(`Error: ${err}`, 160) : 'Error'
  }
  if (item.status === 'cancelled') return 'Cancelled'
  if (output) {
    const text =
      output.text ??
      output.content ??
      output.result ??
      output.message ??
      output.output ??
      null
    if (typeof text === 'string' && text.length > 0) return trim(text, 160)
    return stringifyValue(output, 160)
  }
  if (item.output) return trim(item.output, 160)
  return 'Done'
}

/** Pull the message text out of a send_message action's input. Falls back
 *  to a stringified dump if no recognised field is present. */
export function formatMessage(input: Record<string, unknown> | null): string {
  if (!input) return ''
  const msg = input.message ?? input.text ?? input.content
  if (typeof msg === 'string') return trim(msg, 220)
  return stringifyValue(input, 220)
}
