/**
 * The line under the composer. Left: what the keys do right now (the
 * shortcut hint, the armed leader, "press again to quit"). Right: the open
 * session, other sessions that are busy or have something unread, the
 * reasoning effort, the cache hit rate of the last request, running Agent
 * Apps and the connection.
 *
 *   ? keys · Ctrl+X screens               Main ○ · effort high · cache 82%
 */
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../state/hooks'
import { selectSessions } from '../../../browser/frontend/src/store/selectors/sessions'
import { selectLastMessageIdBySession } from '../../../browser/frontend/src/store/selectors/messages'
import { selectUiState } from '../../../browser/frontend/src/store/selectors/ui'
import { UI_STATE } from '../../../browser/frontend/src/store/uiState'
import { glyphs, ink } from '../theme/theme'
import { truncate, width } from '../text/width'
import { stripEmoji } from '../text/emoji'

export interface StatusLineProps {
  columns: number
  /** Left side; the shortcut hint when not given. */
  hint?: string
  /** Color of the left side (the leader and quit prompts stand out). */
  hintColor?: string
}

export function StatusLine({ columns, hint, hintColor }: StatusLineProps) {
  const { t } = useTranslation('tui')
  const g = glyphs()
  const active = useAppSelector(s => s.tui.activeSessionId)
  const connected = useAppSelector(s => s.connection.connected)
  const backendBusy = useAppSelector(s => s.connection.backendBusy)
  const runState = useAppSelector(s => s.agent.runStateBySession)
  const sessions = useAppSelector(selectSessions)
  const lastIds = useAppSelector(selectLastMessageIdBySession)
  const seen = useAppSelector(s => selectUiState(s, UI_STATE.chat.lastSeenMessageIds)) as Record<string, string>
  const runningApps = useAppSelector(s => s.agentApp.projects.filter(p => p.status === 'running').length)

  const titleOf = (id: string) =>
    id === 'main'
      ? t('session.main')
      : id === 'new'
        ? t('session.newChat')
        : stripEmoji(sessions.find(s => s.id === id)?.title ?? '') || t('session.untitled')
  const session = sessions.find(s => s.id === active)

  // The first part is the open session; parts are dropped from the end of
  // the middle until the line fits.
  const parts: { text: string; color?: string }[] = []
  parts.push({ text: `${truncate(titleOf(active), 24)} ${runState[active] !== undefined ? g.busy : g.idle}`, color: ink.brand })
  if (!connected) parts.push({ text: t('status.offline'), color: ink.error })
  else if (backendBusy) parts.push({ text: t('status.backendBusy'), color: ink.warn })

  // Other sessions that need a look: busy, or with an unread last message.
  let others = 0
  for (const s of sessions) {
    if (s.id === active || s.type === 'agent_app') continue
    const busy = runState[s.id] !== undefined
    const unread = !!lastIds[s.id] && lastIds[s.id] !== seen[s.id]
    if (!busy && !unread) continue
    if (others < 2) parts.push({ text: `${truncate(titleOf(s.id), 14)} ${busy ? g.busy : g.unread}`, color: busy ? undefined : ink.info })
    others++
  }
  if (others > 2) parts.push({ text: t('status.moreSessions', { count: others - 2 }) })

  if (session?.reasoningEffort && session.reasoningEffort !== 'provider_default') {
    parts.push({ text: t('status.effort', { value: session.reasoningEffort }) })
  }
  const last = session?.lastRequest
  if (last && last.inputTokens > 0) {
    parts.push({ text: t('status.cache', { value: Math.round((100 * (last.cachedTokens ?? 0)) / last.inputTokens) }) })
  }
  if (runningApps > 0) parts.push({ text: t('status.apps', { count: runningApps }) })

  const left = hint ?? t('status.help')
  const sep = ` ${g.sep} `
  const room = columns - 3
  const rightWidth = (list: typeof parts) => width(list.map(p => p.text).join(sep))
  while (parts.length > 1 && width(left) + 2 + rightWidth(parts) > room) parts.pop()
  const leftShown = truncate(left, Math.max(0, room - rightWidth(parts) - 2))
  const gap = Math.max(1, room - width(leftShown) - rightWidth(parts))

  return (
    <Box paddingLeft={2}>
      <Text color={hintColor ?? ink.muted}>{leftShown}</Text>
      <Text>{' '.repeat(gap)}</Text>
      {parts.map((p, i) => (
        <Text key={i}>
          {i > 0 ? <Text color={ink.dim}>{sep}</Text> : null}
          <Text color={p.color ?? ink.muted}>{truncate(p.text, room)}</Text>
        </Text>
      ))}
    </Box>
  )
}
