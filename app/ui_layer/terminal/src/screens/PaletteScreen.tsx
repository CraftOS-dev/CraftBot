/**
 * Ctrl+P: one fuzzy search over everything that can be opened or run:
 * screens, sessions, Agent Apps, slash commands and skills.
 */
import { Pointer, rowMetaStyle, rowStyle } from '../ui/selection'
import { useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector } from '../state/hooks'
import { closeAllScreens, replaceScreen, setActiveSession, type ScreenId } from '../state/tuiSlice'
import { selectChatSessions } from '../../../browser/frontend/src/store/selectors/sessions'
import { setPendingPrefill } from '../../../browser/frontend/src/store/slices/chatInputSlice'
import { RESOURCES, useResource } from '../../../browser/frontend/src/store/resources'
import { Frame, bodyRows } from '../ui/Frame'
import { useScreen, useScreenKeys } from './context'
import { clampList, listKey, LIST_START } from '../ui/list'
import { TextField, fieldKey } from '../ui/TextField'
import * as TB from '../input/TextBuffer'
import { LOCAL_COMMANDS } from '../keymap/leader'
import { glyphs, ink } from '../theme/theme'
import { padEnd, truncate } from '../text/width'
import { startNewChat } from '../runtime/actions'

interface Entry {
  label: string
  detail: string
  kind: string
  run: () => void
}

/** Subsequence match score: lower is better, null when it does not match. */
export function fuzzyScore(text: string, query: string): number | null {
  if (!query) return 0
  const hay = text.toLowerCase()
  const needle = query.toLowerCase()
  const direct = hay.indexOf(needle)
  if (direct !== -1) return direct
  let pos = 0
  let gaps = 0
  for (const ch of needle) {
    const found = hay.indexOf(ch, pos)
    if (found === -1) return null
    gaps += found - pos
    pos = found + 1
  }
  return 100 + gaps
}

export function PaletteScreen() {
  const { t } = useTranslation('tui')
  const dispatch = useAppDispatch()
  const { columns, rows, setTextFocus } = useScreen()
  useResource(RESOURCES.commands)
  useResource(RESOURCES.skills)
  const chats = useAppSelector(selectChatSessions)
  const apps = useAppSelector(s => s.agentApp.projects)
  const commands = useAppSelector(s => s.commandsSettings.commands)
  const skills = useAppSelector(s => s.skillsSettings.skills)
  const [query, setQuery] = useState<TB.Buffer>(TB.EMPTY)
  const [list, setList] = useState(LIST_START)

  const go = (screen: ScreenId, arg?: string) => () => dispatch(replaceScreen({ id: screen, arg }))
  const prefill = (text: string) => () => {
    dispatch(setPendingPrefill(text))
    dispatch(closeAllScreens())
  }
  const entries: Entry[] = [
    ...LOCAL_COMMANDS.filter(c => c.screen && c.name !== 'keys').map(c => ({
      label: t(c.label),
      detail: `/${c.name}`,
      kind: t('palette.screen'),
      run: go(c.screen as ScreenId),
    })),
    { label: t('screens.help'), detail: '?', kind: t('palette.screen'), run: go('help') },
    { label: t('actions.newChat'), detail: 'Ctrl+N', kind: t('palette.action'), run: () => startNewChat() },
    {
      label: t('session.main'),
      detail: '',
      kind: t('palette.session'),
      run: () => {
        dispatch(setActiveSession('main'))
        dispatch(closeAllScreens())
      },
    },
    ...chats.map(s => ({
      label: s.title || t('session.untitled'),
      detail: '',
      kind: t('palette.session'),
      run: () => {
        dispatch(setActiveSession(s.id))
        dispatch(closeAllScreens())
      },
    })),
    ...apps.map(p => ({ label: p.name, detail: p.status, kind: t('palette.app'), run: go('app', p.id) })),
    ...commands.map(c => ({ label: `/${c.name.replace(/^\//, '')}`, detail: c.description, kind: t('palette.command'), run: prefill(`/${c.name.replace(/^\//, '')} `) })),
    ...skills
      .filter(s => s.enabled && s.user_invocable)
      .map(s => ({ label: `/${s.name}`, detail: s.description, kind: t('palette.skill'), run: prefill(`/${s.name} `) })),
  ]

  const q = query.text.trim()
  const matches = entries
    .map(e => ({ e, score: fuzzyScore(`${e.label} ${e.detail}`, q) }))
    .filter((m): m is { e: Entry; score: number } => m.score !== null)
    .sort((a, b) => a.score - b.score)
    .map(m => m.e)
  const height = bodyRows(rows) - 2
  const view = clampList(list, matches.length, height)

  useScreenKeys((input, key) => {
    setTextFocus(true)
    if (key.return) {
      matches[view.index]?.run()
      return true
    }
    if (key.upArrow || key.downArrow || key.pageUp || key.pageDown) {
      const next = listKey(view, '', key, matches.length, height)
      if (next) setList(next)
      return true
    }
    const next = fieldKey(query, input, key)
    if (next) {
      setQuery(next)
      setList(LIST_START)
      return true
    }
    return false
  })

  const g = glyphs()
  return (
    <Frame
      title={t('screens.palette')}
      aside={t('palette.count', { count: matches.length })}
      hints={[{ keys: 'Enter', label: t('hint.run') }, { keys: 'Up/Down', label: t('hint.move') }, { keys: 'Esc', label: t('hint.back') }]}
      columns={columns}
      rows={rows}
    >
      <Box flexDirection="column">
        <TextField label={g.prompt} buffer={query} focused width={columns} placeholder={t('palette.placeholder')} />
        <Text> </Text>
        {matches.slice(view.top, view.top + height).map((entry, i) => {
          const selected = view.top + i === view.index
          return (
            <Box key={`${entry.kind}:${entry.label}:${i}`}>
              <Pointer selected={selected} />
              <Text {...rowStyle(selected)}>{padEnd(entry.label, Math.min(40, Math.floor(columns * 0.45)))}</Text>
              <Text {...rowMetaStyle(selected, true, ink.muted)}>{padEnd(entry.kind, 10)}</Text>
              <Text {...rowMetaStyle(selected, true, ink.muted)}>
                {padEnd(truncate(entry.detail, Math.max(0, columns - Math.min(40, Math.floor(columns * 0.45)) - 14)), Math.max(0, columns - Math.min(40, Math.floor(columns * 0.45)) - 13))}
              </Text>
            </Box>
          )
        })}
      </Box>
    </Frame>
  )
}
