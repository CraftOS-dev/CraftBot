import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { WifiOff } from 'lucide-react'
import { ConfirmModal } from '../../components/ui'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useToast } from '../../contexts/ToastContext'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { selectSessionRunState } from '../../store/selectors/agent'
import { selectConnected } from '../../store/selectors/connection'
import {
  selectMiniBrowserAdblock,
  selectMiniBrowserAgentBusy,
  selectMiniBrowserError,
  selectMiniBrowserEvents,
  selectMiniBrowserFollow,
  selectMiniBrowserInstall,
  selectMiniBrowserKnown,
  selectMiniBrowserNavResult,
  selectMiniBrowserSessionId,
  selectMiniBrowserSettings,
  selectMiniBrowserStatus,
  selectMiniBrowserTabs,
  selectMiniBrowserViewedTab,
  selectMiniBrowserViewport,
} from '../../store/selectors/miniBrowser'
import { setPendingPrefill } from '../../store/slices/chatInputSlice'
import {
  installRequested,
  navResultDismissed,
  type MiniBrowserEventEntry,
} from '../../store/slices/miniBrowserSlice'
import type { MiniBrowserTab } from '../../types'
import { ChatPanel } from './ChatPanel'
import { canOpenDownload, downloadName, isDangerousDownload, stripFormatControls } from './downloads'
import { LiveView, type LiveViewHandle } from './live/LiveView'
import { PasswordsModal } from './PasswordsModal'
import { StatusPanel, type PanelState } from './StatusPanel'
import { TabStrip } from './TabStrip'
import { Toolbar, type AddressTarget, type StopTarget, type ToolbarHandle } from './Toolbar'
import { sendAction, sendLive, useMiniBrowserViewer } from './useMiniBrowserSocket'
import { useErrorText } from './useErrorText'
import { useLatest } from './useLatest'
import { useTabLabels } from './useTabLabels'
import styles from './MiniBrowserPage.module.css'

/** The session whose run drives a tab: its owner, or a sub-agent's parent. */
function driverSession(tab: MiniBrowserTab): string | null {
  if (tab.ownerKind === 'user') return null
  if (tab.ownerKind === 'subagent') return tab.parentOwner
  return tab.owner
}

/**
 * The Mini Browser: a live view of the real Chromium that the user and every
 * agent share, with tabs, an address bar, take-over controls, saved logins,
 * and the dedicated Mini Browser chat beside it.
 */
export function MiniBrowserPage() {
  const { t } = useTranslation(['minibrowser', 'common'])
  const dispatch = useAppDispatch()
  const { stopSession, openFile, openFolder } = useWebSocket()
  const { showToast } = useToast()
  const { ownerName } = useTabLabels()
  const errorText = useErrorText()

  const connected = useAppSelector(selectConnected)
  const known = useAppSelector(selectMiniBrowserKnown)
  const status = useAppSelector(selectMiniBrowserStatus)
  const error = useAppSelector(selectMiniBrowserError)
  const sessionId = useAppSelector(selectMiniBrowserSessionId)
  const tabs = useAppSelector(selectMiniBrowserTabs)
  const viewedTab = useAppSelector(selectMiniBrowserViewedTab)
  const follow = useAppSelector(selectMiniBrowserFollow)
  const adblock = useAppSelector(selectMiniBrowserAdblock)
  const settings = useAppSelector(selectMiniBrowserSettings)
  const viewport = useAppSelector(selectMiniBrowserViewport)
  const install = useAppSelector(selectMiniBrowserInstall)
  const navResult = useAppSelector(selectMiniBrowserNavResult)
  const events = useAppSelector(selectMiniBrowserEvents)
  const agentBusy = useAppSelector(selectMiniBrowserAgentBusy)

  // The Stop button stops the run driving the viewed tab.
  const driver = viewedTab ? driverSession(viewedTab) : null
  const driverRunState = useAppSelector(state => (driver ? selectSessionRunState(state, driver) : 'idle'))
  const driverActive = !!viewedTab?.busy || driverRunState !== 'idle'
  const stopTarget = useMemo<StopTarget | null>(
    () => (driver && driverActive ? { sessionId: driver, runState: driverRunState } : null),
    [driver, driverActive, driverRunState],
  )

  const stageAreaRef = useRef<HTMLDivElement>(null)
  const liveViewRef = useRef<LiveViewHandle>(null)
  const toolbarRef = useRef<ToolbarHandle>(null)

  // Viewer subscription + remote viewport sizing.
  useMiniBrowserViewer(stageAreaRef, connected, viewport)

  // ── Browser actions ───────────────────────────────────────────────────
  const viewedTabId = viewedTab?.id ?? null
  const tabsRef = useLatest(tabs)
  const followRef = useLatest(follow)
  const viewedTabRef = useLatest(viewedTab)

  // The address bar opens what was typed in the tab the edit started on —
  // never in whichever tab came on screen meanwhile (that may be an agent's).
  const navigate = useCallback((text: string, target: AddressTarget) => {
    dispatch(navResultDismissed())
    const tab = target.tabId ? tabsRef.current.find(t => t.id === target.tabId) : undefined
    // An agent claimed the tab while the user was typing (handing it back to
    // the user is fine: that tab is theirs to navigate).
    const claimedMeanwhile = !!tab && tab.owner !== null && tab.owner !== target.owner
    if (tab && !claimedMeanwhile) {
      // Show the tab that is about to load.
      if (tab.id !== viewedTabRef.current?.id) sendAction('mini_browser_tab', { action: 'switch', tabId: tab.id })
      sendAction('mini_browser_navigate', { tabId: tab.id, url: text })
    } else if (!target.tabId && tabsRef.current.length === 0) {
      // Nothing is open yet: the backend starts the browser and opens one.
      sendAction('mini_browser_navigate', { url: text })
    } else {
      // The tab was closed, or an agent took it over meanwhile: open the
      // address in a new tab of the user's own instead.
      sendAction('mini_browser_tab', { action: 'new', url: text })
    }
  }, [dispatch, tabsRef, viewedTabRef])

  const history = useCallback((action: 'back' | 'forward' | 'reload' | 'stop') => {
    sendAction('mini_browser_history', viewedTabId ? { tabId: viewedTabId, action } : { action })
  }, [viewedTabId])

  const newTab = useCallback(() => {
    sendAction('mini_browser_tab', { action: 'new' })
  }, [])

  const switchTab = useCallback((tabId: string) => {
    sendAction('mini_browser_tab', { action: 'switch', tabId })
  }, [])

  const [confirmCloseTab, setConfirmCloseTab] = useState<MiniBrowserTab | null>(null)
  const [confirmShutdown, setConfirmShutdown] = useState(false)

  const closeTabNow = useCallback((tabId: string) => {
    sendAction('mini_browser_tab', { action: 'close', tabId })
  }, [])

  const requestCloseTab = useCallback((tab: MiniBrowserTab) => {
    // Closing a tab an agent is working in interrupts it: ask first.
    if (tab.busy && tab.ownerKind !== 'user' && !tab.userControl) setConfirmCloseTab(tab)
    else closeTabNow(tab.id)
  }, [closeTabNow])

  const setFollow = useCallback((next: boolean) => {
    sendAction('mini_browser_view', { follow: next })
  }, [])

  // While the user works in a tab, "follow" must not pull the view away to
  // whichever tab an agent touches next (mid-typing, mid-IME-composition,
  // mid-CAPTCHA): any deliberate input — a click, a key, text, the wheel,
  // taking control — stops following. Hovering does not count.
  const stopFollowing = useCallback(() => {
    if (!followRef.current) return
    followRef.current = false
    sendLive('mini_browser_view', { follow: false })
  }, [followRef])

  const setAdblock = useCallback((enabled: boolean) => {
    sendAction('mini_browser_adblock', { enabled })
  }, [])

  const setControl = useCallback((take: boolean) => {
    if (!viewedTabId) return
    if (take) stopFollowing()
    sendAction('mini_browser_control', { tabId: viewedTabId, take })
  }, [stopFollowing, viewedTabId])

  const start = useCallback(() => sendAction('mini_browser_start'), [])

  const installBrowser = useCallback(() => {
    dispatch(installRequested())
    sendAction('mini_browser_install')
  }, [dispatch])

  const requestShutdown = useCallback(() => {
    if (agentBusy) setConfirmShutdown(true)
    else sendAction('mini_browser_shutdown')
  }, [agentBusy])

  const stopAgent = useCallback(() => {
    if (stopTarget && stopTarget.runState !== 'stopping') stopSession(stopTarget.sessionId)
  }, [stopSession, stopTarget])

  const onUserInput = stopFollowing

  const focusAddress = useCallback(() => toolbarRef.current?.focusAddress(), [])
  const focusPage = useCallback(() => liveViewRef.current?.focus(), [])

  const contentRef = useRef<HTMLDivElement>(null)
  // The chat sits under the browser (ChatPanel decides from the row's width).
  const [stacked, setStacked] = useState(false)
  // Bumped to make ChatPanel show the chat.
  const [chatOpenSignal, setChatOpenSignal] = useState(0)

  // ── Notices from the browser (dialogs, downloads, blocks, crashes) ────
  // The headline is always in the user's language; the backend's own
  // sentence (English, written for agents) only ever appears as the detail
  // line with the specifics: the address and why, what the dialog said.
  const announceDownload = useCallback((event: MiniBrowserEventEntry) => {
    const path = event.path
    if (!path) {
      showToast('success', t('minibrowser:events.downloadUnnamed'))
      return
    }
    const name = downloadName(path)
    const showInFolder = { label: t('minibrowser:events.showInFolder'), onClick: () => openFolder(path) }
    // A page can download without a click. A file that can run code is never
    // one click away from running: a warning, and only "Show in folder".
    if (isDangerousDownload(name, event.dangerous)) {
      showToast('warning', t('minibrowser:events.download', { name }), undefined, {
        detail: t('minibrowser:events.downloadDangerous'),
        actions: [showInFolder],
      })
      return
    }
    showToast('success', t('minibrowser:events.download', { name }), undefined, {
      actions: canOpenDownload(name, event.dangerous)
        ? [{ label: t('minibrowser:events.openFile'), onClick: () => openFile(path) }, showInFolder]
        : [showInFolder],
    })
  }, [openFile, openFolder, showToast, t])

  const announce = useCallback((event: MiniBrowserEventEntry) => {
    const onViewedTab = !event.tabId || event.tabId === viewedTabRef.current?.id
    const type = event.level === 'error' ? 'error' : event.level === 'warning' ? 'warning' : 'info'
    const detail = stripFormatControls(event.message).trim()
    switch (event.kind) {
      case 'download':
        announceDownload(event)
        return
      case 'crash':
        showToast('error', t('minibrowser:events.crash'))
        return
      case 'blocked':
        showToast('warning', t('minibrowser:events.blockedGeneric'), undefined, { detail })
        return
      case 'dialog':
        // Dialogs and popups matter on the tab being watched; on an agent's
        // other tabs the agent is told about them itself.
        if (onViewedTab) showToast('info', t('minibrowser:events.dialogGeneric'), undefined, { detail })
        return
      case 'popup':
        if (onViewedTab) showToast('info', t('minibrowser:events.popup'))
        return
      case 'notice':
        showToast(type, t('minibrowser:events.notice'), undefined, { detail })
        return
      default:
        // A failed request carries its error code: show the localized title
        // with the backend's specifics.
        if (event.code) {
          const text = errorText({ code: event.code, title: event.title ?? '', message: event.message })
          showToast(type, [text.title, text.detail || text.message].filter(Boolean).join(' — '))
        } else if (detail) {
          showToast(type, t(event.kind === 'error' ? 'minibrowser:events.problem' : 'minibrowser:events.notice'),
            undefined, { detail })
        }
    }
  }, [announceDownload, errorText, showToast, t, viewedTabRef])

  // Only events that arrive while the page is open are announced.
  const announcedSeqRef = useRef<number | null>(null)
  useEffect(() => {
    const newest = events.length > 0 ? events[events.length - 1].seq : 0
    const since = announcedSeqRef.current
    announcedSeqRef.current = newest
    if (since === null) return
    for (const event of events) {
      if (event.seq > since) announce(event)
    }
  }, [events, announce])

  // A finished install says so (failures show in the status panel).
  const installDoneRef = useRef(install.doneSeq)
  useEffect(() => {
    if (install.doneSeq === installDoneRef.current) return
    installDoneRef.current = install.doneSeq
    if (install.ok) showToast('success', t('minibrowser:status.installDone'))
  }, [install.doneSeq, install.ok, showToast, t])

  // ── Derived view state ────────────────────────────────────────────────
  const panelState: PanelState | null = !known ? 'connecting' : status === 'ready' ? null : status
  const browserOpen = known && status !== 'stopped' && status !== 'installing'
  const navError = navResult && !navResult.ok ? navResult.error : null
  const tabIdsKey = useMemo(() => tabs.map(tab => tab.id).join('\n'), [tabs])

  const [passwordsOpen, setPasswordsOpen] = useState(false)

  const onExample = useCallback((prompt: string) => {
    dispatch(setPendingPrefill(prompt))
    setChatOpenSignal(n => n + 1)
  }, [dispatch])

  return (
    <div className={styles.page}>
      <div ref={contentRef} className={`${styles.content} ${stacked ? styles.contentStacked : ''}`}>
        <section className={styles.browserPanel} aria-label={t('minibrowser:page.label')}>
          <Toolbar
            ref={toolbarRef}
            tab={viewedTab}
            follow={follow}
            adblock={adblock}
            browserOpen={browserOpen}
            navError={navError}
            stopTarget={stopTarget}
            onNavigate={navigate}
            onHistory={history}
            onFollow={setFollow}
            onAdblock={setAdblock}
            onOpenPasswords={() => setPasswordsOpen(true)}
            onCloseBrowser={requestShutdown}
            onStopAgent={stopAgent}
            onDismissNavError={() => dispatch(navResultDismissed())}
            onSubmitted={focusPage}
          />
          <TabStrip
            tabs={tabs}
            viewedTabId={viewedTabId}
            onSwitch={switchTab}
            onClose={requestCloseTab}
            onNew={newTab}
          />
          {/* Fixed-size area: its size is the remote viewport (see useMiniBrowserViewer).
              The live view stays mounted in every state so a frame that
              arrives just before "ready" is never lost; the status panel
              covers it until the browser is ready. */}
          <div ref={stageAreaRef} className={styles.stageArea}>
            <LiveView
              ref={liveViewRef}
              active={panelState === null}
              tab={viewedTab}
              tabIdsKey={tabIdsKey}
              connected={connected}
              showCursor={settings.showCursor}
              ownerName={viewedTab ? ownerName(viewedTab) : ''}
              onFocusAddress={focusAddress}
              onHistory={history}
              onControl={setControl}
              onNewTab={newTab}
              onUserInput={onUserInput}
            />
            {panelState !== null && (
              <StatusPanel
                state={panelState}
                error={error}
                installLines={install.lines}
                chatAvailable={!!sessionId}
                onStart={start}
                onInstall={installBrowser}
                onOpenSite={focusAddress}
                onExample={onExample}
              />
            )}
            {viewedTab?.loading && panelState === null && <div className={styles.loadingBar} aria-hidden="true" />}
            {!connected && (
              <div className={styles.disconnected} role="status">
                <WifiOff size={22} />
                <strong>{t('minibrowser:live.reconnecting')}</strong>
                <span>{t('minibrowser:live.reconnectingHint')}</span>
              </div>
            )}
          </div>
        </section>

        <ChatPanel
          containerRef={contentRef}
          sessionId={sessionId}
          onStackedChange={setStacked}
          openSignal={chatOpenSignal}
        />
      </div>

      {passwordsOpen && <PasswordsModal isOpen={passwordsOpen} onClose={() => setPasswordsOpen(false)} />}

      <ConfirmModal
        isOpen={!!confirmCloseTab}
        title={t('minibrowser:tabs.closeBusyTitle')}
        message={confirmCloseTab
          ? t('minibrowser:tabs.closeBusyMessage', { owner: ownerName(confirmCloseTab) })
          : ''}
        confirmText={t('minibrowser:tabs.close')}
        variant="danger"
        onConfirm={() => {
          if (confirmCloseTab) closeTabNow(confirmCloseTab.id)
          setConfirmCloseTab(null)
        }}
        onCancel={() => setConfirmCloseTab(null)}
      />
      <ConfirmModal
        isOpen={confirmShutdown}
        title={t('minibrowser:confirm.shutdownTitle')}
        message={t('minibrowser:confirm.shutdownMessage')}
        confirmText={t('minibrowser:toolbar.closeBrowser')}
        variant="danger"
        onConfirm={() => {
          setConfirmShutdown(false)
          sendAction('mini_browser_shutdown')
        }}
        onCancel={() => setConfirmShutdown(false)}
      />
    </div>
  )
}
