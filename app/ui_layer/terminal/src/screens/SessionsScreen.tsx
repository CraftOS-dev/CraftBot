/**
 * Every conversation: Main pinned first (things that happen on their own
 * arrive there), then all chats by latest activity, with no "show more".
 * Busy and unread glyphs, a filter, and rename, clear, delete and
 * create-skill actions.
 */
import { Pointer, rowMetaStyle, rowStyle } from '../ui/selection'
import { useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../state/hooks'
import { closeAllScreens, pushToast, setActiveSession } from '../state/tuiSlice'
import { selectChatSessions, selectMainSession } from '../../../browser/frontend/src/store/selectors/sessions'
import { selectLastMessageIdBySession } from '../../../browser/frontend/src/store/selectors/messages'
import { selectUiState } from '../../../browser/frontend/src/store/selectors/ui'
import { UI_STATE } from '../../../browser/frontend/src/store/uiState'
import { RESOURCES, useResource } from '../../../browser/frontend/src/store/resources'
import { Frame, bodyRows } from '../ui/Frame'
import { useScreen, useScreenKeys } from './context'
import { clampList, listKey, LIST_START } from '../ui/list'
import { TextField, fieldKey } from '../ui/TextField'
import { ConfirmLine, confirmKey, type PendingConfirm } from '../ui/Confirm'
import * as TB from '../input/TextBuffer'
import { glyphs, ink } from '../theme/theme'
import { padEnd, truncate } from '../text/width'
import { startNewChat } from '../runtime/actions'

function relativeTime(iso: string, locale: string): string {
  const then = Date.parse(iso)
  if (!Number.isFinite(then)) return ''
  const seconds = Math.round((then - Date.now()) / 1000)
  const fmt = new Intl.RelativeTimeFormat(locale, { numeric: 'auto', style: 'short' })
  const abs = Math.abs(seconds)
  if (abs < 60) return fmt.format(seconds, 'second')
  if (abs < 3600) return fmt.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return fmt.format(Math.round(seconds / 3600), 'hour')
  return fmt.format(Math.round(seconds / 86400), 'day')
}

export function SessionsScreen() {
  const { t, i18n } = useTranslation('tui')
  const dispatch = useAppDispatch()
  const { columns, rows, setTextFocus } = useScreen()
  useResource(RESOURCES.sessions)
  const main = useAppSelector(selectMainSession)
  const chats = useAppSelector(selectChatSessions)
  const active = useAppSelector(s => s.tui.activeSessionId)
  const runState = useAppSelector(s => s.agent.runStateBySession)
  const lastIds = useAppSelector(selectLastMessageIdBySession)
  const seen = useAppSelector(s => selectUiState(s, UI_STATE.chat.lastSeenMessageIds)) as Record<string, string>

  const [filter, setFilter] = useState<TB.Buffer>(TB.EMPTY)
  const [filtering, setFiltering] = useState(false)
  const [renaming, setRenaming] = useState<{ id: string; buf: TB.Buffer } | null>(null)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [list, setList] = useState(LIST_START)

  const query = filter.text.trim().toLowerCase()
  const all = [...(main ? [main] : []), ...chats]
  const items = query ? all.filter(s => (s.id === 'main' ? t('session.main') : s.title).toLowerCase().includes(query)) : all
  const height = bodyRows(rows) - 2
  const view = clampList(list, items.length, height)
  const selected = items[view.index]

  const setFieldFocus = (focused: boolean) => setTextFocus(focused)

  useScreenKeys((input, key) => {
    if (confirmKey(confirm, input, key, () => setConfirm(null))) return true
    if (renaming) {
      if (key.escape) {
        setRenaming(null)
        setFieldFocus(false)
        return true
      }
      if (key.return) {
        const title = renaming.buf.text.trim()
        if (title) send('session_rename', { sessionId: renaming.id, title })
        setRenaming(null)
        setFieldFocus(false)
        return true
      }
      const next = fieldKey(renaming.buf, input, key)
      if (next) setRenaming({ ...renaming, buf: next })
      return true
    }
    if (filtering) {
      if (key.escape || key.return) {
        setFiltering(false)
        setFieldFocus(false)
        if (key.escape) setFilter(TB.EMPTY)
        return true
      }
      if (key.upArrow || key.downArrow) {
        const next = listKey(view, '', key, items.length, height)
        if (next) setList(next)
        return true
      }
      const next = fieldKey(filter, input, key)
      if (next) {
        setFilter(next)
        setList(LIST_START)
      }
      return true
    }
    const moved = listKey(view, input, key, items.length, height)
    if (moved) {
      setList(moved)
      return true
    }
    if (input === '/') {
      setFiltering(true)
      setFieldFocus(true)
      return true
    }
    if (input === 'n') {
      startNewChat()
      return true
    }
    if (!selected) return false
    if (key.return || input === 'l' || key.rightArrow) {
      dispatch(setActiveSession(selected.id))
      dispatch(closeAllScreens())
      return true
    }
    if (input === 'r' && selected.type === 'chat') {
      setRenaming({ id: selected.id, buf: TB.fromText(selected.title) })
      setFieldFocus(true)
      return true
    }
    if (input === 'c') {
      setConfirm({
        message: t('sessions.confirmClear', { title: selected.id === 'main' ? t('session.main') : selected.title }),
        onConfirm: () => send('session_clear', { sessionId: selected.id }),
      })
      return true
    }
    if (input === 'd' && selected.type === 'chat') {
      setConfirm({
        message: t('sessions.confirmDelete', { title: selected.title }),
        onConfirm: () => {
          send('session_delete', { sessionId: selected.id })
          if (selected.id === active) dispatch(setActiveSession('main'))
        },
      })
      return true
    }
    if (input === 'k') {
      send('create_skill_from_session', { sessionId: selected.id })
      dispatch(pushToast(t('sessions.skillRequested'), 'info'))
      return true
    }
    return false
  })

  const g = glyphs()
  return (
    <Frame
      title={t('screens.sessions')}
      aside={t('sessions.count', { count: all.length })}
      hints={[
        { keys: 'Enter', label: t('hint.open') },
        { keys: 'n', label: t('actions.newChat') },
        { keys: 'r', label: t('hint.rename') },
        { keys: 'c', label: t('hint.clear') },
        { keys: 'd', label: t('hint.delete') },
        { keys: 'k', label: t('hint.makeSkill') },
        { keys: '/', label: t('hint.filter') },
        { keys: 'Esc', label: t('hint.back') },
      ]}
      columns={columns}
      rows={rows}
    >
      <Box flexDirection="column">
        {filtering || query ? (
          <TextField label="/" buffer={filter} focused={filtering} width={columns} placeholder={t('hint.filter')} />
        ) : (
          <Text color={ink.muted}>{truncate(t('sessions.mainNote'), columns - 1)}</Text>
        )}
        <Text> </Text>
        {items.slice(view.top, view.top + height).map((session, i) => {
          const index = view.top + i
          const isSelected = index === view.index
          const busy = runState[session.id] !== undefined
          const unread = !!lastIds[session.id] && lastIds[session.id] !== seen[session.id] && session.id !== active
          const mark = busy ? g.busy : unread ? g.unread : ' '
          const title = session.id === 'main' ? t('session.main') : session.title || t('session.untitled')
          const when = relativeTime(session.lastActiveAt || session.createdAt, i18n.language)
          const isRenaming = renaming?.id === session.id
          return (
            <Box key={session.id}>
              <Pointer selected={isSelected} />
              <Text color={busy ? ink.brand : unread ? ink.info : ink.muted}>{mark} </Text>
              {isRenaming ? (
                <TextField buffer={renaming.buf} focused width={columns - 6} />
              ) : (
                <>
                  <Text {...rowStyle(isSelected, true, session.id === active ? ink.brand : undefined)}>
                    {padEnd(title, Math.max(10, columns - 22))}
                  </Text>
                  <Text {...rowMetaStyle(isSelected, true, ink.muted)}>{padEnd(truncate(when, 16), 18)}</Text>
                </>
              )}
            </Box>
          )
        })}
        {confirm ? <ConfirmLine pending={confirm} columns={columns} hint={t('hint.confirm')} /> : null}
      </Box>
    </Frame>
  )
}
