/**
 * One transient notice: a glyph that carries its tone, then the message.
 *
 *   ✓ Saved          ✗ Could not send: offline          · Attached 2 files
 */
import { Text } from 'ink'
import type { Toast } from '../state/tuiSlice'
import { glyphs, ink } from '../theme/theme'
import { truncate } from '../text/width'

export function ToastLine({ toast, columns }: { toast: Toast; columns: number }) {
  const g = glyphs()
  const [glyph, color] =
    toast.tone === 'error' ? [g.failed, ink.error] : toast.tone === 'success' ? [g.done, ink.success] : [g.notice, ink.muted]
  return (
    <Text>
      <Text color={color}>{` ${glyph} `}</Text>
      <Text color={toast.tone === 'info' ? ink.muted : undefined}>{truncate(toast.message, Math.max(4, columns - 4))}</Text>
    </Text>
  )
}
