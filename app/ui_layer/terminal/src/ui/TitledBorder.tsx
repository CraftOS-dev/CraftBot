/**
 * The top or bottom edge of a box with a label set into the line, for a Box
 * drawn next to it with borderTop={false} (or borderBottom={false}). Labels
 * cost no rows: titles and counters ride the top edge, key hints the bottom.
 *
 *   ╭─ Settings › Model ──────────────────────────── 3 providers ─╮
 *   ╰─ Enter open · Esc back ─────────────────────────────────────╯
 *
 * A title with " › " renders as a breadcrumb: crumbs in the title color, the
 * separators dim, the last crumb bold.
 */
import { Text } from 'ink'
import { glyphs, ink } from '../theme/theme'
import { truncate, width } from '../text/width'
import type { KeyHint } from './Frame'

export interface TitledBorderProps {
  title?: string
  /** Key hints set into the edge instead of a title (bottom edges). */
  hints?: KeyHint[]
  /** Right side, set into the line before the corner. */
  aside?: string
  columns: number
  edge?: 'top' | 'bottom'
  color?: string
  titleColor?: string
  /** Bold last crumb (titles); off for a sentence set into an edge. */
  titleBold?: boolean
  asideColor?: string
}

const CRUMB = ' › '

/** Hints that fit the room; the last one (usually "Esc back") always stays. */
export function fitHints(hints: KeyHint[], room: number, sep: string): KeyHint[] {
  const shown = hints.slice()
  const size = (list: KeyHint[]) => width(list.map(h => `${h.keys} ${h.label}`).join(sep))
  while (shown.length > 1 && size(shown) > room) shown.splice(shown.length - 2, 1)
  return shown
}

export function HintText({ hints, sep }: { hints: KeyHint[]; sep: string }) {
  return (
    <>
      {hints.map((h, i) => (
        <Text key={i}>
          {i > 0 ? <Text color={ink.dim}>{sep}</Text> : null}
          <Text bold>{h.keys}</Text>
          <Text color={ink.muted}>{` ${h.label}`}</Text>
        </Text>
      ))}
    </>
  )
}

function Crumbs({ title, color, bold }: { title: string; color?: string; bold: boolean }) {
  const parts = title.split(CRUMB)
  return (
    <>
      {parts.map((part, i) => (
        <Text key={i}>
          {i > 0 ? <Text color={ink.dim}>{CRUMB}</Text> : null}
          <Text color={color} bold={bold && i === parts.length - 1}>{part}</Text>
        </Text>
      ))}
    </>
  )
}

export function TitledBorder({ title, hints, aside, columns, edge = 'top', color, titleColor, titleBold = true, asideColor }: TitledBorderProps) {
  const g = glyphs()
  const [left, right] = edge === 'top' ? [g.boxTopLeft, g.boxTopRight] : [g.boxBottomLeft, g.boxBottomRight]
  const sep = ` ${g.sep} `
  // Corner, rule, space on the left; space, rule, corner on the right.
  const room = Math.max(0, columns - 6)
  const asideText = aside ? truncate(aside, Math.floor(room / 2)) : ''
  const labelRoom = Math.max(0, room - (asideText ? width(asideText) + 3 : 0))
  const shownHints = hints ? fitHints(hints, labelRoom, sep) : []
  const hintWidth = width(shownHints.map(h => `${h.keys} ${h.label}`).join(sep))
  const titleText = title ? truncate(title, labelRoom) : ''
  const labelWidth = hints ? Math.min(hintWidth, labelRoom) : width(titleText)
  const hasLabel = labelWidth > 0
  const fill = Math.max(0, columns - 4 - (hasLabel ? labelWidth + 2 : 0) - (asideText ? width(asideText) + 2 : 0))
  return (
    <Text wrap="truncate-end">
      <Text color={color}>{`${left}${g.boxH}`}</Text>
      {hasLabel ? <Text color={color}> </Text> : null}
      {hints ? <HintText hints={shownHints} sep={sep} /> : titleText ? <Crumbs title={titleText} color={titleColor} bold={titleBold} /> : null}
      {hasLabel ? <Text color={color}> </Text> : null}
      <Text color={color}>{g.boxH.repeat(fill)}</Text>
      {asideText ? (
        <>
          <Text color={color}> </Text>
          <Text color={asideColor}>{asideText}</Text>
          <Text color={color}> </Text>
        </>
      ) : null}
      <Text color={color}>{`${g.boxH}${right}`}</Text>
    </Text>
  )
}
