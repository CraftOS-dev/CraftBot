/**
 * Mini Browser (Ctrl+X b): the open chat's own browser as a table of tabs
 * (owner, title, address, state). In the terminal edition the browser runs
 * as a window on the user's desktop: taking control of the agent's tab
 * brings its window to the front and pauses the agent there until the user
 * hands it back from this screen. Also: stop the agent's run, close a tab
 * (asking first when an agent works in it), copy a tab's link, start the
 * browser, and install Chromium with its progress log.
 *
 * The screen watches the browser with the panel's own messages
 * (mini_browser_subscribe / unsubscribe). Watching a stopped browser starts
 * it, so the screen only watches one that already runs, or once the user
 * starts it here.
 */
import { useEffect, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { MiniBrowserError, MiniBrowserTab } from '../../../browser/frontend/src/types'
import { useAppDispatch, useAppSelector } from '../state/hooks'
import { RESOURCES, useResource } from '../../../browser/frontend/src/store/resources'
import { selectConnected } from '../../../browser/frontend/src/store/selectors/connection'
import { selectSessions } from '../../../browser/frontend/src/store/selectors/sessions'
import {
  selectMiniBrowserActivity,
  selectMiniBrowserEvents,
  selectMiniBrowserInstall,
  selectMiniBrowserTabs,
  selectMiniBrowserView,
} from '../../../browser/frontend/src/store/selectors/miniBrowser'
import { installRequested, type MiniBrowserEventEntry } from '../../../browser/frontend/src/store/slices/miniBrowserSlice'
import { sendAction, sendLive } from '../../../browser/frontend/src/components/MiniBrowser/useMiniBrowserSocket'
import { Frame, bodyRows, type KeyHint } from '../ui/Frame'
import { clampList, listKey, LIST_START } from '../ui/list'
import { ConfirmLine, confirmKey, type PendingConfirm } from '../ui/Confirm'
import { useScreen, useScreenKeys } from './context'
import { glyphs, ink } from '../theme/theme'
import { oneLine, padEnd, truncate, width } from '../text/width'
import { stopSession } from '../chat/intents'
import { sessionTitle } from '../chat/transcriptWriter'
import { copyToClipboard } from './viewClipboard'
import {
  canInstall,
  canToggleControl,
  displayUrl,
  driverSession,
  needsCloseConfirm,
  ownerKind,
  tabState,
  type TabState,
} from './viewBrowser'

interface Notice {
  text: string
  tone: 'info' | 'error'
}

const STATE_COLOR: Record<TabState, string | undefined> = {
  crashed: ink.error,
  control: ink.info,
  working: ink.brand,
  loading: ink.muted,
  idle: ink.muted,
}

function stateGlyph(state: TabState): string {
  const g = glyphs()
  switch (state) {
    case 'crashed':
      return g.failed
    case 'control':
      return g.unread
    case 'working':
      return g.busy
    default:
      return g.idle
  }
}

/** Hints that fit the footer, dropping the least important first. */
function fitHints(hints: (KeyHint & { priority: number })[], columns: number): KeyHint[] {
  const shown = [...hints]
  const total = () => width(shown.map(h => `${h.keys} ${h.label}`).join('   '))
  while (shown.length > 1 && total() > columns - 1) {
    let lowest = 0
    for (let i = 1; i < shown.length; i++) if (shown[i].priority < shown[lowest].priority) lowest = i
    shown.splice(lowest, 1)
  }
  return shown
}

export function BrowserScreen(_props: { arg?: string }) {
  const { t } = useTranslation(['screensView', 'minibrowser', 'tui'])
  const dispatch = useAppDispatch()
  const { columns, rows } = useScreen()
  useResource(RESOURCES.miniBrowserActivity)

  const sessionId = useAppSelector(s => s.tui.activeSessionId)
  const title = useAppSelector(s => sessionTitle(s, sessionId))
  const connected = useAppSelector(selectConnected)
  const activity = useAppSelector(s => selectMiniBrowserActivity(s, sessionId))
  const view = useAppSelector(s => selectMiniBrowserView(s, sessionId))
  const tabs = useAppSelector(s => selectMiniBrowserTabs(s, sessionId))
  const install = useAppSelector(selectMiniBrowserInstall)
  const events = useAppSelector(selectMiniBrowserEvents)
  const sessions = useAppSelector(selectSessions)
  const runState = useAppSelector(s => s.agent.runStateBySession)

  const [started, setStarted] = useState(false)
  const [list, setList] = useState(LIST_START)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)

  // Watch the browser while it runs (or failed: watching retries and shows
  // why), or once the user started it here.
  const isNew = sessionId === 'new'
  const watching = !isNew && connected && (started || (!!activity && activity.status !== 'stopped'))
  useEffect(() => {
    if (!watching) return
    sendLive('mini_browser_subscribe', { sessionId })
    return () => {
      sendLive('mini_browser_unsubscribe', { sessionId })
    }
  }, [watching, sessionId])

  const status = !watching ? 'stopped' : view?.status ?? 'starting'
  const error = view?.error ?? null
  const installable = canInstall(status, error, install.ok)

  // Only events that arrive while the screen is open are shown.
  const seenSeq = useRef<number>(events.length ? events[events.length - 1].seq : 0)
  useEffect(() => {
    const fresh = events.filter(e => e.seq > seenSeq.current && (e.sessionId === sessionId || e.sessionId === null))
    if (events.length) seenSeq.current = events[events.length - 1].seq
    const last = fresh[fresh.length - 1]
    if (last) setNotice({ text: eventText(last), tone: last.level === 'error' ? 'error' : 'info' })
    // eventText only reads translations: the events decide.
  }, [events, sessionId])

  // An install that finishes says so.
  const installDone = useRef(install.doneSeq)
  useEffect(() => {
    if (install.doneSeq === installDone.current) return
    installDone.current = install.doneSeq
    if (install.ok) setNotice({ text: t('browser.installDone'), tone: 'info' })
    else if (install.error) setNotice({ text: t('browser.installFailed', { error: errorLine(install.error) }), tone: 'error' })
  }, [install.doneSeq, install.ok, install.error, t])

  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(timer)
  }, [notice])

  function errorLine(err: MiniBrowserError): string {
    const titleText = t(`minibrowser:errors.${err.code}.title`, { defaultValue: err.title || err.code })
    const message = t(`minibrowser:errors.${err.code}.message`, { defaultValue: err.message })
    return [titleText, message].filter(Boolean).join(': ')
  }

  function eventText(event: MiniBrowserEventEntry): string {
    const detail = oneLine(event.message ?? '')
    if (event.code) return errorLine({ code: event.code, title: event.title ?? '', message: event.message })
    const headline = (() => {
      switch (event.kind) {
        case 'download':
          return t('browser.event.download', { name: event.path ? event.path.split(/[\\/]/).pop() : '' })
        case 'crash':
          return t('browser.event.crash')
        case 'blocked':
          return t('browser.event.blocked')
        case 'dialog':
          return t('browser.event.dialog')
        case 'popup':
          return t('browser.event.popup')
        case 'error':
          return t('browser.event.problem')
        default:
          return t('browser.event.notice')
      }
    })()
    return event.kind === 'download' || !detail ? headline : `${headline}: ${detail}`
  }

  function ownerName(tab: MiniBrowserTab): string {
    const kind = ownerKind(tab, sessionId)
    if (kind !== 'session') return t(`browser.owner.${kind}`)
    const session = sessions.find(s => s.id === tab.owner)
    return session?.title.trim() || tab.ownerLabel.trim() || t('browser.owner.session')
  }

  function tabTitle(tab: MiniBrowserTab): string {
    return oneLine(tab.title) || (tab.url && tab.url !== 'about:blank' ? displayUrl(tab.url) : t('browser.untitled'))
  }

  const ready = status === 'ready'
  const shownTabs = ready ? tabs : []
  const tableRows = Math.max(1, bodyRows(rows) - 6)
  const listView = clampList(list, shownTabs.length, tableRows)
  const selected: MiniBrowserTab | undefined = shownTabs[listView.index]
  const controlled = shownTabs.find(tab => tab.userControl)

  const flash = (text: string, tone: Notice['tone'] = 'info') => setNotice({ text, tone })

  const toggleControl = (tab: MiniBrowserTab) => {
    if (tab.userControl) {
      sendAction('mini_browser_control', { sessionId, tabId: tab.id, take: false })
      flash(t('browser.controlReturned'))
      return
    }
    // Bring the tab's window to the front, then pause the agent on it.
    sendAction('mini_browser_tab', { sessionId, action: 'switch', tabId: tab.id })
    sendAction('mini_browser_control', { sessionId, tabId: tab.id, take: true })
    flash(t('browser.controlTaken'))
  }

  const closeTab = (tab: MiniBrowserTab) => {
    const close = () => sendAction('mini_browser_tab', { sessionId, action: 'close', tabId: tab.id })
    if (!needsCloseConfirm(tab)) {
      close()
      return
    }
    setConfirm({ message: t('browser.confirmClose', { owner: ownerName(tab), title: truncate(tabTitle(tab), 30) }), onConfirm: close })
  }

  const stopAgent = () => {
    const candidates = [selected, ...shownTabs].filter((tab): tab is MiniBrowserTab => !!tab)
    const driver = candidates
      .map(tab => ({ tab, driver: driverSession(tab) }))
      .find(c => c.driver && (c.tab.busy || runState[c.driver] !== undefined))?.driver
    if (!driver) {
      flash(t('browser.notBrowsing'))
      return
    }
    if (runState[driver] !== 'stopping') stopSession(driver)
    flash(t('browser.stopping'))
  }

  const start = () => {
    setStarted(true)
    if (watching && (status === 'stopped' || status === 'error')) sendAction('mini_browser_start', { sessionId })
  }

  const installChromium = () => {
    dispatch(installRequested())
    sendAction('mini_browser_install')
  }

  useScreenKeys((input, key) => {
    if (confirmKey(confirm, input, key, () => setConfirm(null))) return true
    const moved = listKey(listView, input, key, shownTabs.length, tableRows)
    if (moved) {
      setList(moved)
      return true
    }
    if (isNew) return false
    if (input === 's' && (status === 'stopped' || status === 'error')) {
      start()
      return true
    }
    if (input === 'i' && installable) {
      installChromium()
      return true
    }
    if (input === 'x') {
      stopAgent()
      return true
    }
    if (!selected) return false
    if (input === 't' && canToggleControl(selected)) {
      toggleControl(selected)
      return true
    }
    if (key.return) {
      sendAction('mini_browser_tab', { sessionId, action: 'switch', tabId: selected.id })
      return true
    }
    if (input === 'd') {
      closeTab(selected)
      return true
    }
    if (input === 'c') {
      const url = selected.url
      void copyToClipboard(url)
        .then(how => flash(how === 'system' ? t('browser.linkCopied') : t('browser.linkCopiedTerminal')))
        .catch((err: unknown) => flash(t('browser.copyFailed', { error: String((err as Error)?.message ?? err) }), 'error'))
      return true
    }
    return false
  })

  // --- layout ------------------------------------------------------------------
  const g = glyphs()
  const asideParts = [t(`browser.status.${status}`)]
  if (ready) asideParts.push(t('browser.tabs', { count: tabs.length }))
  if (activity?.browsing) asideParts.push(t('browser.browsing'))

  const ownerNames = shownTabs.map(ownerName)
  const stateNames = shownTabs.map(tab => t(`browser.state.${tabState(tab)}`))
  const ownerW = Math.min(14, Math.max(width(t('browser.col.owner')), ...ownerNames.map(n => width(n)), 3))
  const stateW = Math.min(16, Math.max(width(t('browser.col.state')), ...stateNames.map(n => width(n)), 4))
  const flexible = Math.max(10, columns - 4 - ownerW - stateW - 6)
  const titleW = Math.max(5, Math.floor(flexible * 0.45))
  const addressW = Math.max(5, flexible - titleW)

  const hints = fitHints(
    [
      ...(selected && canToggleControl(selected)
        ? [{ keys: 't', label: selected.userControl ? t('browser.hint.handBack') : t('browser.hint.control'), priority: 10 }]
        : []),
      ...(selected ? [{ keys: 'Enter', label: t('browser.hint.show'), priority: 4 }] : []),
      ...(selected ? [{ keys: 'd', label: t('browser.hint.close'), priority: 7 }] : []),
      ...(selected ? [{ keys: 'c', label: t('browser.hint.copy'), priority: 6 }] : []),
      ...(ready && shownTabs.some(tab => driverSession(tab)) ? [{ keys: 'x', label: t('browser.hint.stop'), priority: 8 }] : []),
      ...(!isNew && (status === 'stopped' || status === 'error') ? [{ keys: 's', label: t('browser.hint.start'), priority: 9 }] : []),
      ...(installable ? [{ keys: 'i', label: t('browser.hint.install'), priority: 11 }] : []),
      { keys: 'Esc', label: t('browser.hint.back'), priority: 5 },
    ],
    columns,
  )

  const statusLine = (() => {
    if (isNew) return { text: t('browser.newChat'), color: ink.muted }
    switch (status) {
      case 'stopped':
        return { text: t('browser.off'), color: ink.muted }
      case 'starting':
        return { text: t('browser.starting'), color: ink.muted }
      case 'installing':
        return { text: t('browser.installing'), color: ink.info }
      case 'error':
        return { text: error ? errorLine(error) : t('browser.status.error'), color: ink.error }
      default:
        return { text: controlled ? t('browser.controlTaken') : t('browser.controlNote'), color: controlled ? ink.info : ink.muted }
    }
  })()

  const showLog = status === 'installing' || (install.lines.length > 0 && install.ok === false)
  const logRows = Math.max(1, bodyRows(rows) - 4)

  return (
    <Frame
      title={t('browser.title', { session: title })}
      aside={asideParts.join(' · ')}
      hints={hints}
      columns={columns}
      rows={rows}
    >
      <Box flexDirection="column">
        <Text color={statusLine.color} wrap="truncate-end">{truncate(statusLine.text, columns - 1)}</Text>
        {installable && status === 'error' ? (
          <Text color={ink.muted}>{truncate(t('browser.installHint'), columns - 1)}</Text>
        ) : null}
        <Text> </Text>
        {ready ? (
          <>
            <Text color={ink.muted}>
              {'    ' +
                padEnd(t('browser.col.owner'), ownerW) + '  ' +
                padEnd(t('browser.col.title'), titleW) + '  ' +
                padEnd(t('browser.col.address'), addressW) + '  ' +
                padEnd(t('browser.col.state'), stateW)}
            </Text>
            {shownTabs.length === 0 ? <Text color={ink.muted}>{`    ${t('browser.noTabs')}`}</Text> : null}
            {shownTabs.slice(listView.top, listView.top + tableRows).map((tab, i) => {
              const index = listView.top + i
              const isSelected = index === listView.index
              const state = tabState(tab)
              return (
                <Box key={tab.id}>
                  <Text color={isSelected ? ink.focus : undefined}>{isSelected ? `${g.pointer} ` : '  '}</Text>
                  <Text color={STATE_COLOR[state]}>{`${stateGlyph(state)} `}</Text>
                  <Text bold={isSelected}>{padEnd(ownerNames[index], ownerW)}</Text>
                  <Text>{'  '}</Text>
                  <Text bold={isSelected}>{padEnd(tabTitle(tab), titleW)}</Text>
                  <Text>{'  '}</Text>
                  <Text color={ink.muted}>{padEnd(displayUrl(tab.url), addressW)}</Text>
                  <Text>{'  '}</Text>
                  <Text color={STATE_COLOR[state]}>{padEnd(stateNames[index], stateW)}</Text>
                </Box>
              )
            })}
          </>
        ) : null}
        {showLog
          ? install.lines.slice(-logRows).map((line, i) => (
              <Text key={`log-${i}`} color={ink.muted} wrap="truncate-end">
                {truncate(line, columns - 1)}
              </Text>
            ))
          : null}
        {confirm ? (
          <ConfirmLine pending={confirm} columns={columns} hint={t('tui:hint.confirm')} />
        ) : notice ? (
          <Text color={notice.tone === 'error' ? ink.error : ink.info} wrap="truncate-end">
            {truncate(notice.text, columns - 1)}
          </Text>
        ) : null}
      </Box>
    </Frame>
  )
}
