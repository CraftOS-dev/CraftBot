/** Draw the view engine's styled lines with the terminal's colors. */
import { Box, Text } from 'ink'
import type { Line, Tone } from '../../../../../agent-app/view/src/index.ts'
import { ink } from '../theme/theme'

function color(tone: Tone | undefined): { color?: string; bold?: boolean; inverse?: boolean } {
  switch (tone) {
    case 'muted':
      return { color: ink.muted }
    case 'bold':
      return { bold: true }
    case 'accent':
      return { color: ink.brand }
    case 'heading':
      return { color: ink.brand, bold: true }
    case 'error':
      return { color: ink.error }
    case 'success':
      return { color: ink.success }
    case 'selected':
      return ink.focus ? { color: ink.focus, bold: true } : { inverse: true }
    default:
      return {}
  }
}

export function ViewLines({ lines }: { lines: Line[] }) {
  return (
    <Box flexDirection="column">
      {lines.map((line, i) => (
        <Text key={i} wrap="truncate">
          {line.length === 0
            ? ' '
            : line.map((segment, j) => (
                <Text key={j} {...color(segment.tone)}>
                  {segment.text}
                </Text>
              ))}
        </Text>
      ))}
    </Box>
  )
}
