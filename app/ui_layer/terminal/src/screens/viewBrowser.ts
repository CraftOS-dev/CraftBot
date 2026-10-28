/**
 * The Browser screen's rules, kept free of React so they can be tested:
 * which run drives a tab, what state a tab is in, when closing a tab needs a
 * confirmation and when Chromium can be installed. Same rules as the
 * browser's SessionBrowserPanel and StatusPanel.
 */
import type {
  MiniBrowserError,
  MiniBrowserStatus,
  MiniBrowserTab,
} from '../../../browser/frontend/src/types'

/** The session whose run drives a tab: its owner, or a sub-agent's parent. */
export function driverSession(tab: MiniBrowserTab): string | null {
  if (tab.ownerKind === 'user') return null
  if (tab.ownerKind === 'subagent') return tab.parentOwner
  return tab.owner
}

export type TabState = 'crashed' | 'control' | 'working' | 'loading' | 'idle'

export function tabState(tab: MiniBrowserTab): TabState {
  if (tab.crashed) return 'crashed'
  if (tab.userControl) return 'control'
  if (tab.busy && tab.ownerKind !== 'user') return 'working'
  if (tab.loading) return 'loading'
  return 'idle'
}

/** Closing a tab an agent is working in interrupts it: ask first. */
export function needsCloseConfirm(tab: MiniBrowserTab): boolean {
  return tab.busy && tab.ownerKind !== 'user' && !tab.userControl
}

/** Taking control makes sense on an agent's tab; handing back on one the user controls. */
export function canToggleControl(tab: MiniBrowserTab): boolean {
  return tab.userControl || tab.ownerKind !== 'user'
}

const INSTALL_CODES: ReadonlySet<string> = new Set(['MINI_BROWSER_CHROMIUM_MISSING', 'MINI_BROWSER_PLAYWRIGHT_MISSING'])

/** Chromium (or Playwright) is missing, or the last install failed. */
export function canInstall(status: MiniBrowserStatus, error: MiniBrowserError | null, lastInstallOk: boolean | null): boolean {
  if (status !== 'error') return false
  return (!!error && INSTALL_CODES.has(error.code)) || lastInstallOk === false
}

export type OwnerKind = 'you' | 'agent' | 'subagent' | 'main' | 'session'

/** Who uses a tab, from the point of view of the session whose browser it is. */
export function ownerKind(tab: MiniBrowserTab, sessionId: string): OwnerKind {
  if (tab.ownerKind === 'user') return 'you'
  if (tab.ownerKind === 'subagent') return 'subagent'
  if (tab.owner === sessionId) return 'agent'
  if (tab.ownerKind === 'main' || tab.owner === 'main') return 'main'
  return 'session'
}

/** An address as shown in the table: no scheme, no trailing slash on a bare host. */
export function displayUrl(url: string): string {
  if (!url || url === 'about:blank') return url || ''
  return url.replace(/^https?:\/\//i, '').replace(/^www\./i, '').replace(/^([^/?#]+)\/$/, '$1')
}
