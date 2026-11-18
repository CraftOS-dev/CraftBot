/**
 * The frame every full-screen screen shares: a bordered panel with the title
 * (a breadcrumb) set into the top edge, the status on the right of that
 * edge, and the key hints on the row under the panel.
 *
 *   ╭─ Sessions ─────────────────────────────────── 12 chats ─╮
 *   │                                                         │
 *   │ ❯ ● Main                                       just now │
 *   │     Trip to Kyoto                                 2h ago │
 *   ╰─────────────────────────────────────────────────────────╯
 *    Enter open · n new chat · / filter          Esc back · ? help
 *
 * `columns` is the width the screen lays its rows out to (the screen root
 * hands screens the terminal width minus FRAME_SIDES); the frame adds its
 * border and one cell of padding on each side.
 */
import type { ReactNode } from 'react'
import { Box, Text } from 'ink'
import i18n from '../platform/i18n'
import { borderStyle, glyphs, ink } from '../theme/theme'
import { width } from '../text/width'
import { HintText, TitledBorder, fitHints } from './TitledBorder'

export interface KeyHint {
  keys: string
  label: string
}

export interface FrameProps {
  title: string
  /** Right side of the title edge (status, counts). */
  aside?: string
  hints: KeyHint[]
  columns: number
  rows: number
  children: ReactNode
}

/** Cells the frame adds around a screen's content: border and padding, both sides. */
export const FRAME_SIDES = 4

const hintWidth = (hints: KeyHint[], sep: string) => width(hints.map(h => `${h.keys} ${h.label}`).join(sep))

/**
 * The key-hint row: the screen's own keys on the left, the way out ("Esc
 * back") and help on the right. Hints that do not fit drop from the middle.
 */
export function HintBar({ hints, columns }: { hints: KeyHint[]; columns: number }) {
  const g = glyphs()
  const sep = ` ${g.sep} `
  const back = hints.filter(h => h.keys === 'Esc')
  const own = hints.filter(h => h.keys !== 'Esc')
  const right = [...back, { keys: '?', label: i18n.t('tui:hint.help') }]
  const room = columns - 2
  const rightShown = hintWidth(right, sep) + 2 <= room ? right : back
  const leftShown = fitHints(own, Math.max(0, room - hintWidth(rightShown, sep) - 2), sep)
  const gap = Math.max(1, room - hintWidth(leftShown, sep) - hintWidth(rightShown, sep))
  return (
    <Box paddingLeft={1} width={columns}>
      <Text wrap="truncate-end">
        <HintText hints={leftShown} sep={sep} />
        <Text>{' '.repeat(gap)}</Text>
        <HintText hints={rightShown} sep={sep} />
      </Text>
    </Box>
  )
}

export function Frame({ title, aside, hints, columns, rows, children }: FrameProps) {
  const outer = columns + FRAME_SIDES
  return (
    <Box flexDirection="column" width={outer} height={rows}>
      <TitledBorder
        title={title}
        aside={aside}
        columns={outer}
        color={ink.border}
        titleColor={ink.brand}
        asideColor={ink.muted}
      />
      <Box
        flexDirection="column"
        borderStyle={borderStyle()}
        borderTop={false}
        borderColor={ink.border}
        paddingX={1}
        width={outer}
        height={rows - 2}
      >
        <Text> </Text>
        <Box flexDirection="column" height={bodyRows(rows)} overflow="hidden">
          {children}
        </Box>
      </Box>
      <HintBar hints={hints} columns={outer} />
    </Box>
  )
}

/** Rows available inside a Frame's body. */
export function bodyRows(rows: number): number {
  return Math.max(1, rows - 4)
}
