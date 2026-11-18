/**
 * Add Agent App: the browser's Add modal as a screen with three tabs.
 *
 *   Marketplace  search, tag filters, "Installed xN", setup questions as a form
 *   Create       the wizard: configure, interview, then the build starts
 *   Import       a GitHub URL, a folder, or a ZIP path, with progress lines
 *
 * `[` and `]` switch tabs whenever no text field has focus. Esc inside a tab
 * moves focus up to the tab bar (Left/Right switch there, Enter or Down goes
 * back in); Esc on the tab bar leaves, asking first if typed input would be
 * lost. After a create, install or import the screen becomes the new app's.
 *
 * Opened with the argument `wizard` (hostJobs does this when a chat summons
 * setup questions), it starts on Create at the interview step.
 */
import { useCallback, useEffect, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch } from '../../state/hooks'
import { closeScreen, replaceScreen } from '../../state/tuiSlice'
import { Frame, bodyRows } from '../../ui/Frame'
import { useScreen, useScreenKeys } from '../context'
import { glyphs, ink } from '../../theme/theme'
import { truncate, width } from '../../text/width'
import { takeWizardSeed, WIZARD_SEED_ARG, type WizardSeed } from './hostJobs'
import { useMarketTab } from './hostMarketTab'
import { useWizardTab } from './hostWizardTab'
import { useImportTab } from './hostImportTab'

const TABS = ['marketplace', 'create', 'import'] as const
type TabId = (typeof TABS)[number]

export function AppCreateScreen({ arg }: { arg?: string }) {
  const { t } = useTranslation('appsHost')
  const dispatch = useAppDispatch()
  const { columns, rows, setTextFocus } = useScreen()
  const [seed] = useState<WizardSeed | null>(() => (arg === WIZARD_SEED_ARG ? takeWizardSeed() : null))
  const [tab, setTab] = useState<TabId>(seed ? 'create' : 'marketplace')
  const [barFocus, setBarFocus] = useState(false)
  const [confirmLeave, setConfirmLeave] = useState(false)

  const onOpenProject = useCallback((projectId: string) => dispatch(replaceScreen({ id: 'app', arg: projectId })), [dispatch])
  // Body rows: tab bar, a blank line, then the tab.
  const height = Math.max(4, bodyRows(rows) - 2)
  const props = { t, columns, height, onOpenProject }
  const market = useMarketTab({ ...props, active: tab === 'marketplace' && !barFocus })
  const wizard = useWizardTab({ ...props, active: tab === 'create' && !barFocus, seed })
  const importer = useImportTab({ ...props, active: tab === 'import' && !barFocus })
  const current = tab === 'marketplace' ? market : tab === 'create' ? wizard : importer
  const textFocus = !barFocus && !confirmLeave && current.textFocus
  const dirty = wizard.dirty || importer.dirty

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
