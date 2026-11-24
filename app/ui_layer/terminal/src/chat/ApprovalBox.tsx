/**
 * The pinned box above the composer while an action waits for the user's
 * approval (Settings > Security, Auto mode off): the action, why it asks,
 * its inputs, the time left and three numbered choices. Like the question
 * box it never takes typing by itself: Tab moves focus into it, then digits
 * or arrows and Enter, or a / s / d, answer; Esc gives focus back.
 *
 *   ╭─ Approval needed · Run shell command ─── 1 of 2 · 4:32 left ─╮
 *   │ Auto mode is off, and this action can run commands or code.  │
 *   │ command: rm -rf build                                        │
 *   │ ❯ 1. Allow once                                              │
 *   │   2. Allow for this session                                  │
 *   │   3. Deny                                                    │
 *   ╰─ Tab to answer · no answer in time counts as Deny ───────────╯
 *
 * No answer before the time runs out counts as a denial (the backend's).
 */
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { ApprovalRequest } from '../../../browser/frontend/src/store/slices/securitySlice'
import { borderStyle, chip, glyphs, ink } from '../theme/theme'
import { padEnd, truncate } from '../text/width'
import { TitledBorder } from '../ui/TitledBorder'
import { useTicker } from '../ui/useTicker'
import { APPROVAL_CHOICES, approvalBody, approvalSecondsLeft, approvalTimeLeft } from './approval'

/** Under this many seconds the time left turns to the warning color. */
const HURRY_S = 30

export interface ApprovalBoxProps {
  request: ApprovalRequest
  total: number
  focused: boolean
  selected: number
  columns: number
  maxInputLines: number
  /** The chat it was asked in, when that is not the open one. */
  sessionLabel?: string
}

export function ApprovalBox({ request, total, focused, selected, columns, maxInputLines, sessionLabel }: ApprovalBoxProps) {
  const { t, i18n } = useTranslation('tui')
  useTicker(1000)
  const g = glyphs()
  const inner = Math.max(10, columns - 4)
  const now = Date.now()
  const left = approvalSecondsLeft(request.expires_at, now)
  const name = request.action_display_name || request.action_name
  const title = t('approval.title', { action: name })
  const time = approvalTimeLeft(request.expires_at, now)
  const aside = total > 1 ? t('approval.timeLeftCount', { time, index: 1, total }) : t('approval.timeLeft', { time })
  const hint = focused ? t('approval.focusedHint') : t('approval.hint')
  const edge = focused ? ink.focus : ink.warn
  const body = approvalBody(request, inner, maxInputLines, t, { language: i18n.language, sessionLabel })

  return (
    <Box flexDirection="column" width={columns}>
      <TitledBorder
        title={title}
        aside={aside}
        columns={columns}
        color={edge}
        titleColor={ink.warn}
        asideColor={left <= HURRY_S ? ink.error : ink.muted}
      />
      <Box flexDirection="column" borderStyle={borderStyle()} borderTop={false} borderBottom={false} borderColor={edge} paddingX={1} width={columns}>
        {body.map((line, i) => (
          <Text key={i} color={line.tone === 'muted' ? ink.muted : undefined} bold={line.tone === 'reason'} wrap="truncate-end">
            {line.tone === 'input' ? <Text color={ink.muted}>{line.text}</Text> : line.text}
          </Text>
        ))}
        {APPROVAL_CHOICES.map((choice, i) => {
          const active = focused && i === selected
          const label = truncate(`${i + 1}. ${t(choice.label)}`, Math.max(8, inner - 2))
          return (
            <Text key={choice.decision}>
              <Text color={ink.focus} bold>{active ? `${g.pointer} ` : '  '}</Text>
              <Text color={active ? chip.fg : undefined} backgroundColor={active ? chip.bg : undefined} bold={active}>
                {active && chip.bg ? padEnd(label, inner - 2) : label}
              </Text>
            </Text>
          )
        })}
      </Box>
      <TitledBorder title={hint} columns={columns} edge="bottom" color={edge} titleColor={ink.muted} titleBold={false} />
    </Box>
  )
}

/** Rows the box takes, for the live region's height budget (same `t` and options as the box). */
export function approvalBoxHeight(
  request: ApprovalRequest,
  columns: number,
  maxInputLines: number,
  t: (key: string, options?: Record<string, unknown>) => string,
  options: { language?: string; sessionLabel?: string } = {},
): number {
  const inner = Math.max(10, columns - 4)
  // Top edge, the body, one row per choice, bottom edge.
  return 1 + approvalBody(request, inner, maxInputLines, t, options).length + APPROVAL_CHOICES.length + 1
}
