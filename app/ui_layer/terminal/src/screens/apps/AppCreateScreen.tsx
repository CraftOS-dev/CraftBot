/**
 * Add Agent App: the browser's Add modal as a screen with four tabs.
 *
 *   Marketplace  the framework's catalogue: search, tag filters, install
 *   Build        describe a new app; the build starts and asks you what it needs
 *   Import       a ZIP, a folder or a GitHub URL, with progress lines
 *   Connect      an Agent App already running somewhere, by its URL
 *
 * `[` and `]` switch tabs whenever no text field has focus. Esc inside a tab
 * moves focus up to the tab bar (Left/Right switch there, Enter or Down goes
 * back in); Esc on the tab bar leaves, asking first if typed input would be
 * lost. After a build starts, an install or import finishes, or a connection
 * is approved, the screen becomes that app's (or that build's).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch } from '../../state/hooks'
import { closeScreen, replaceScreen } from '../../state/tuiSlice'
import { Frame, bodyRows } from '../../ui/Frame'
import { useScreen, useScreenKeys } from '../context'
import { glyphs, ink } from '../../theme/theme'
import { truncate, width } from '../../text/width'
import { useJobs } from './hostJobs'
import { useMarketTab } from './hostMarketTab'
import { useWizardTab } from './hostWizardTab'
import { useImportTab } from './hostImportTab'
import { useConnectTab } from './hostConnectTab'

const TABS = ['marketplace', 'create', 'import', 'connect'] as const
type TabId = (typeof TABS)[number]

export function AppCreateScreen(_props: { arg?: string }) {
  const { t } = useTranslation('appsHost')
  const dispatch = useAppDispatch()
  const { columns, rows, setTextFocus } = useScreen()
  const [tab, setTab] = useState<TabId>('marketplace')
  const [barFocus, setBarFocus] = useState(false)
  const [confirmLeave, setConfirmLeave] = useState(false)

  const onOpenApp = useCallback((appKey: string) => dispatch(replaceScreen({ id: 'app', arg: appKey })), [dispatch])
  const onOpenBuild = useCallback((sessionId: string) => dispatch(replaceScreen({ id: 'app', arg: `pending:${sessionId}` })), [dispatch])
  // Body rows: tab bar, a blank line, then the tab.
  const height = Math.max(4, bodyRows(rows) - 2)
  const props = { t, columns, height, onOpenApp, onOpenBuild }
  const market = useMarketTab({ ...props, active: tab === 'marketplace' && !barFocus })
  const wizard = useWizardTab({ ...props, active: tab === 'create' && !barFocus })
  const importer = useImportTab({ ...props, active: tab === 'import' && !barFocus })
  const connector = useConnectTab({ ...props, active: tab === 'connect' && !barFocus })
  const current = tab === 'marketplace' ? market : tab === 'create' ? wizard : tab === 'import' ? importer : connector
  const textFocus = !barFocus && !confirmLeave && current.textFocus
  const dirty = wizard.dirty || importer.dirty || connector.dirty

  // An install finished, or a conversion started, after this screen opened: go there.
  const { arrival } = useJobs()
  const seen = useRef(arrival?.seq ?? 0)
  useEffect(() => {
    if (!arrival || arrival.seq <= seen.current) return
    seen.current = arrival.seq
    if (arrival.kind === 'app') onOpenApp(arrival.appKey)
    else onOpenBuild(arrival.sessionId)
  }, [arrival, onOpenApp, onOpenBuild])

  useEffect(() => {
    setTextFocus(textFocus)
  }, [textFocus, setTextFocus])
  useEffect(() => () => setTextFocus(false), [setTextFocus])

  const switchTab = (delta: -1 | 1) => setTab(prev => TABS[(TABS.indexOf(prev) + delta + TABS.length) % TABS.length])
  const leave = () => {
    if (dirty) setConfirmLeave(true)
    else dispatch(closeScreen())
  }

  useScreenKeys((input, key) => {
    if (confirmLeave) {
      setConfirmLeave(false)
      if (input === 'y' || input === 'Y') dispatch(closeScreen())
      return true
    }
    if (barFocus) {
      if (key.leftArrow || input === '[' || input === 'h' || (key.tab && key.shift)) switchTab(-1)
      else if (key.rightArrow || input === ']' || input === 'l' || key.tab) switchTab(1)
      else if (key.return || key.downArrow || input === 'j') setBarFocus(false)
      else if (key.escape) leave()
      else return false
      return true
    }
    if (current.handleKey(input, key)) return true
    if (key.escape) {
      setBarFocus(true)
      return true
    }
    if (!current.textFocus && (input === '[' || input === ']')) {
      switchTab(input === ']' ? 1 : -1)
      return true
    }
    return false
  })

  const g = glyphs()
  const labels: Record<TabId, string> = {
    marketplace: t('add.tabs.marketplace'),
    create: t('add.tabs.create'),
    import: t('add.tabs.import'),
    connect: t('add.tabs.connect'),
  }
  const hints = confirmLeave
    ? []
    : barFocus
      ? [
          { keys: 'Left/Right', label: t('hint.switchTab') },
          { keys: 'Enter', label: t('hint.enterTab') },
          { keys: 'Esc', label: t('hint.leave') },
        ]
      : current.hints

  return (
    <Frame title={t('add.title')} hints={hints} columns={columns} rows={rows}>
      <Box>
        <Text color={barFocus ? ink.focus : undefined}>{barFocus ? `${g.pointer} ` : '  '}</Text>
        {TABS.map(id => {
          const on = id === tab
          // Brackets mark the open tab without relying on color.
          const label = on ? `[${labels[id]}]` : ` ${labels[id]} `
          return (
            <Text key={id} bold={on} color={on ? ink.brand : ink.muted} inverse={on && barFocus}>
              {label}
              {'  '}
            </Text>
          )
        })}
      </Box>
      {confirmLeave ? (
        <Box>
          <Text color={ink.warn} bold>{truncate(t('add.confirmLeave'), Math.max(10, columns - width(t('hint.confirm')) - 2))}</Text>
          <Text color={ink.muted}>{'  ' + t('hint.confirm')}</Text>
        </Box>
      ) : (
        <Text> </Text>
      )}
      <Box flexDirection="column" height={height} overflow="hidden">
        {current.body}
      </Box>
    </Frame>
  )
}
