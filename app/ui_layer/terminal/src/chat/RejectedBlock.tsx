/**
 * A message the backend could not accept, above the composer:
 *
 *   ✗ Not sent: the referenced chat could not be read.
 *     ❯ Compare this with last week's numbers
 *     Tab, then r retry · e edit
 *
 * It never reaches the transcript. Retrying sends it again as it was;
 * editing puts its text and references back in the composer.
 */
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { ChatMessage } from '../../../browser/frontend/src/types'
import { glyphs, ink } from '../theme/theme'
import { oneLine, truncate } from '../text/width'

export const REJECTED_ROWS = 3

export function RejectedBlock({ message, focused, columns }: { message: ChatMessage; focused: boolean; columns: number }) {
  const { t } = useTranslation('tui')
  const g = glyphs()
  const text = oneLine(message.content || (message.references ?? []).map(r => r.label).join(', '))
  return (
    <Box flexDirection="column">
      <Text>
        <Text color={ink.error}>{`${g.failed} `}</Text>
        <Text color={ink.error} bold={focused}>{truncate(t('rejected.title', { error: message.submissionError ?? '' }), Math.max(4, columns - 3))}</Text>
      </Text>
      <Text color={ink.muted}>{`  ${g.prompt} ${truncate(text, Math.max(4, columns - 5))}`}</Text>
      <Text color={focused ? ink.focus : ink.dim}>{'  ' + truncate(focused ? t('rejected.focusedKeys') : t('rejected.keys'), Math.max(4, columns - 3))}</Text>
    </Box>
  )
}
