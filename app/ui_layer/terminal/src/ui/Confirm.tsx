/**
 * An inline confirmation line for destructive actions. Cancel is the
 * default; only `y` confirms.
 */
import { Box, Text } from 'ink'
import type { Key } from 'ink'
import { ink } from '../theme/theme'
import { truncate } from '../text/width'

export interface PendingConfirm {
  message: string
  onConfirm: () => void
}

/** Route a key to an open confirmation. Returns true when it handled the key. */
export function confirmKey(pending: PendingConfirm | null, input: string, key: Key, close: () => void): boolean {
  if (!pending) return false
  if (input === 'y' || input === 'Y') {
    pending.onConfirm()
    close()
  } else if (key.escape || input === 'n' || input === 'N' || key.return) {
    close()
  }
  return true
}

export function ConfirmLine({ pending, columns, hint }: { pending: PendingConfirm; columns: number; hint: string }) {
  return (
    <Box>
      <Text color={ink.warn} bold>{truncate(pending.message, Math.max(10, columns - hint.length - 3))}</Text>
      <Text color={ink.muted}>{`  ${hint}`}</Text>
    </Box>
  )
}
