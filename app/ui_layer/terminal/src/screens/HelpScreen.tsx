/**
 * Every key, generated from the same tables the handlers use.
 */
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { Frame } from '../ui/Frame'
import { useScreen, useScreenKeys } from './context'
import { LEADER_BINDINGS } from '../keymap/leader'
import { ink } from '../theme/theme'
import { padEnd, truncate } from '../text/width'
import { useState } from 'react'
import { listKey, LIST_START } from '../ui/list'

export function HelpScreen() {
  const { t } = useTranslation('tui')
  const { columns, rows } = useScreen()
  const [list, setList] = useState(LIST_START)

  const sections: { title: string; rows: [string, string][] }[] = [
    {
      title: t('help.chat'),
      rows: [
        ['Enter', t('help.send')],
        ['Shift+Enter  Ctrl+J  \\ Enter', t('help.newline')],
        ['Esc', t('help.stop')],
        ['Up / Down', t('help.history')],
        ['Tab', t('help.focusQuestion')],
        ['/', t('help.commands')],
        ['Ctrl+O', t('screens.transcript')],
        ['Ctrl+T', t('help.todos')],
        ['Ctrl+N', t('actions.newChat')],
        ['Ctrl+P', t('screens.palette')],
        ['Ctrl+L', t('help.redraw')],
        ['Ctrl+C', t('help.clearOrQuit')],
        ['?', t('screens.help')],
      ],
    },
    {
      title: t('help.leader'),
      rows: LEADER_BINDINGS.map(b => [`Ctrl+X ${b.key}`, t(b.label)] as [string, string]),
    },
    {
      title: t('help.screensTitle'),
      rows: [
        ['j / k  Up / Down', t('help.move')],
        ['Enter  l', t('help.open')],
        ['Esc  h', t('help.back')],
        ['q', t('help.closeAll')],
        ['/', t('help.filter')],
        ['a  e  d', t('help.addEditDelete')],
        ['r', t('help.refresh')],
        ['Tab  [  ]', t('help.panesTabs')],
      ],
    },
    {
      title: t('help.apps'),
      rows: [
        ['Enter', t('help.appOpen')],
        ['l  s', t('help.appLaunchStop')],
        ['a', t('help.appAdd')],
        ['t  p', t('help.appThemeSettings')],
        ['d', t('help.appDelete')],
        ['J  K', t('help.appReorder')],
      ],
    },
    {
      title: t('help.appView'),
      rows: [
        ['Tab  [  ]', t('help.appScreens')],
        ['j  k  n', t('help.appRows')],
        ['Enter', t('help.appRow')],
        [':', t('help.appOps')],
        ['c', t('help.appChat')],
        ['r  o', t('help.appRefreshRecords')],
      ],
    },
    {
      title: t('help.editing'),
      rows: [
        ['Ctrl+A  Ctrl+E  Home  End', t('help.lineEnds')],
        ['Ctrl+Left  Ctrl+Right  Alt+B  Alt+F', t('help.wordMove')],
        ['Ctrl+W  Alt+Backspace', t('help.deleteWord')],
        ['Ctrl+U  Ctrl+K', t('help.killLine')],
      ],
    },
  ]
  const lines: { text: string; heading?: boolean }[] = []
  for (const section of sections) {
    if (lines.length) lines.push({ text: '' })
    lines.push({ text: section.title, heading: true })
    for (const [keys, label] of section.rows) lines.push({ text: `  ${padEnd(keys, 36)}${label}` })
  }
  const height = rows - 4
  useScreenKeys((input, key) => {
    const next = listKey({ index: list.top, top: list.top }, input, key, Math.max(1, lines.length - height + 1), 1)
    if (!next) return false
    setList({ index: next.index, top: next.index })
    return true
  })

  return (
    <Frame title={t('screens.help')} hints={[{ keys: 'j/k', label: t('hint.scroll') }, { keys: 'Esc', label: t('hint.back') }]} columns={columns} rows={rows}>
      <Box flexDirection="column">
        {lines.slice(list.top, list.top + height).map((line, i) => (
          <Text key={i} bold={line.heading} color={line.heading ? ink.brand : undefined}>
            {truncate(line.text, columns - 1)}
          </Text>
        ))}
      </Box>
    </Frame>
  )
}
