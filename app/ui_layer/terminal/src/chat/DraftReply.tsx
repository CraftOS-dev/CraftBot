/**
 * The reply as the agent writes it, laid out as the message it becomes:
 *
 *   ● Booked Sorae for 19:00. The confirmation
 *     number is
 *
 * It shows until the real message arrives (same client id), which then goes
 * to scrollback like any other. The main chat's live region keeps only the
 * newest lines, with the agent mark on the first one shown.
 */
import { Box, Text } from 'ink'
import type { ChatMessage } from '../../../browser/frontend/src/types'
import { renderMessage } from '../render/transcript'
import { glyphs, tone } from '../theme/theme'
import type { DraftReply } from './sessionLive'

/** Cells of the gutter a message hangs under (render/transcript.ts). */
const INDENT = 2

/** The drafts as message lines, a blank line between two of them. */
export function draftLines(drafts: DraftReply[], columns: number): string[] {
  const lines: string[] = []
  for (const draft of drafts) {
    const message: ChatMessage = {
      sender: draft.sender,
      content: draft.text,
      style: 'agent',
      timestamp: draft.startedAt / 1000,
      messageId: `stream:${draft.id}`,
      sessionId: '',
      clientId: draft.id,
    }
    if (lines.length) lines.push('')
    lines.push(...renderMessage(message, columns))
  }
  return lines
}

/** Rows the drafts take in the live region, at most `maxRows`. */
export function draftReplyHeight(drafts: DraftReply[], columns: number, maxRows: number): number {
  if (drafts.length === 0) return 0
  return Math.min(maxRows, draftLines(drafts, columns).length)
}

export function DraftReplyBlock({ drafts, columns, maxRows }: { drafts: DraftReply[]; columns: number; maxRows: number }) {
  const lines = draftLines(drafts, columns)
  if (lines.length === 0) return null
  const shown = lines.slice(-maxRows)
  // Cut from the top: the first line shown carries the mark.
  if (shown.length < lines.length && shown[0].startsWith(' '.repeat(INDENT))) {
    shown[0] = `${tone.brand(glyphs().agent)} ${shown[0].slice(INDENT)}`
  }
  return (
    <Box flexDirection="column">
      {shown.map((line, i) => (
        // An empty Text takes no row; a space keeps the gap between drafts.
        <Text key={i} wrap="truncate-end">{line || ' '}</Text>
      ))}
    </Box>
  )
}
