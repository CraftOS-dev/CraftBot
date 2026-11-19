/**
 * Settings: the browser's nine tabs as a list on the left and the selected
 * tab's form on the right. `[` and `]` (or Tab from the list) change tabs;
 * Enter or Right moves into the tab. Opened with the argument 'effort', it
 * shows the reasoning-effort picker of the open chat instead.
 */
import { Pointer, rowStyle } from '../../ui/selection'
import { useCallback, useMemo, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { Frame } from '../../ui/Frame'
import { useScreen, useScreenKeys } from '../context'
import { glyphs, ink } from '../../theme/theme'
import { padEnd } from '../../text/width'
import { SETTINGS_TABS, type SettingsTabId } from './tabs'
import { EffortPicker } from './EffortPicker'
import { TabContext, type TabKeyHandler } from './tabContext'

const LIST_WIDTH = 18

export function SettingsScreen({ arg }: { arg?: string }) {
  return arg === 'effort' ? <EffortPicker /> : <SettingsTabs arg={arg} />
}

function SettingsTabs({ arg }: { arg?: string }) {
  const { t } = useTranslation('tui')
  const { columns, rows, setTextFocus } = useScreen()
  const initial = SETTINGS_TABS.findIndex(tab => tab.id === arg)
  const [index, setIndex] = useState(Math.max(0, initial))
  const [inTab, setInTab] = useState(initial >= 0)
  // The tab's key handler lives in a ref: registering one must not re-render
  // (a state update here re-registered it on every render, forever).
  const tabHandler = useRef<TabKeyHandler | null>(null)
  const setHandler = useCallback((fn: TabKeyHandler | null) => {
    tabHandler.current = fn
  }, [])
  const [hints, setHints] = useState<{ keys: string; label: string }[]>([])

  const tab = SETTINGS_TABS[index]
  const Tab = tab.component

  useScreenKeys((input, key) => {
    if (inTab) {
      if (tabHandler.current?.(input, key)) return true
      if (key.escape || key.leftArrow) {
        setInTab(false)
        setTextFocus(false)
        return true
      }
      if (input === '[' || input === ']') {
        setIndex(i => (i + (input === ']' ? 1 : -1) + SETTINGS_TABS.length) % SETTINGS_TABS.length)
        return true
      }
      return false
    }
    if (key.upArrow || input === 'k') {
      setIndex(i => (i - 1 + SETTINGS_TABS.length) % SETTINGS_TABS.length)
      return true
    }
    if (key.downArrow || input === 'j' || key.tab) {
      setIndex(i => (i + 1) % SETTINGS_TABS.length)
      return true
    }
    if (key.return || key.rightArrow || input === 'l') {
      setInTab(true)
      return true
    }
    return false
  })

  const g = glyphs()
  const bodyWidth = Math.max(20, columns - LIST_WIDTH - 2)
  const tabContext = useMemo(
    () => ({ active: inTab, width: bodyWidth, height: rows - 4, setHandler, setHints }),
    [inTab, bodyWidth, rows, setHandler],
  )
  return (
    <Frame
      title={t('screens.settings')}
      aside={t(tab.label)}
      hints={inTab ? [...hints, { keys: '[ ]', label: t('settings.otherTab') }, { keys: 'Esc', label: t('settings.tabList') }] : [
        { keys: 'j/k', label: t('hint.move') },
        { keys: 'Enter', label: t('hint.open') },
        { keys: 'Esc', label: t('hint.back') },
      ]}
      columns={columns}
      rows={rows}
    >
      <Box flexDirection="row">
        <Box flexDirection="column" width={LIST_WIDTH}>
          {SETTINGS_TABS.map((entry, i) => {
            const selected = i === index
            return (
              <Text key={entry.id}>
                <Pointer selected={selected} focused={!inTab} />
                <Text {...rowStyle(selected, !inTab, ink.muted)}>{padEnd(t(entry.label), LIST_WIDTH - 3)}</Text>
              </Text>
            )
          })}
        </Box>
        <Text color={ink.muted}>{g.vbar} </Text>
        <Box flexDirection="column" width={bodyWidth}>
          <TabContext.Provider value={tabContext}>
            <Tab key={tab.id} />
          </TabContext.Provider>
        </Box>
      </Box>
    </Frame>
  )
}

export type { SettingsTabId }
