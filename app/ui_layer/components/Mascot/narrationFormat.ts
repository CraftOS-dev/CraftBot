// Shared formatting helpers for the speech bubble's narration content.
// Most action-specific formatting now lives in mascotFormatters.ts (in
// the Tasks/actionRenderers folder, colocated with the per-action card
// renderers). This file keeps only the formatters that aren't tied to a
// specific action — currently just the send_message text extractor.

import type { ActionItem } from '../../browser/frontend/src/types'

/** Truncate `s` to at most `max` chars, appending an ellipsis on truncation. */
function trim(s: string, max: number): string {
  return s.length > max ? s.slice(0, max).trimEnd() + '…' : s
}

/** Render any value to a string, capped at `max` chars. Strings pass through;
 *  everything else goes through JSON.stringify. nullish → empty string. */
function stringifyValue(v: unknown, max = 100): string {
  if (v == null) return ''
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return trim(s, max)
}

/** Pull the message text out of a send_message action's input. Falls back
 *  to a stringified dump if no recognised field is present. */
export function formatMessage(input: Record<string, unknown> | null): string {
  if (!input) return ''
  const msg = input.message ?? input.text ?? input.content
  if (typeof msg === 'string') return trim(msg, 220)
  return stringifyValue(input, 220)
}

// `ActionItem` re-export keeps consumers from needing to reach into the
// browser types directly; it's used by the narration hook for typing.
export type { ActionItem }
