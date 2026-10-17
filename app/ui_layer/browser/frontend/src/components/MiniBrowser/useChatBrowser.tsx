import { useCallback, useEffect, useMemo, useRef } from 'react'
import type { BrowserPanelMode } from '../GenerativeUI/OutputWorkspace'
import { usePersistedState } from '../../hooks'
import { useAppSelector } from '../../store/hooks'
import { RESOURCES, useResource } from '../../store/resources'
import { selectMiniBrowserActivity } from '../../store/selectors/miniBrowser'
import { UI_STATE } from '../../store/uiState'
import { SessionBrowserPanel } from './SessionBrowserPanel'

/**
 * A chat's own browser as its panel's browser mode.
 *
 * Every chat session has a browser of its own. The panel opens on it by
 * itself when the session's agent starts browsing (once per run: the
 * activity's `browsing` turns true), but only for the chat on screen; a
 * chat in the background just shows the activity dot when it comes back.
 * A new Generative UI output takes the panel back (OutputWorkspace).
 * Returns undefined while there is no session yet (a draft chat).
 */
export function useChatBrowser(sessionId: string, enabled: boolean): BrowserPanelMode | undefined {
  // Which session browsers run: fetched on connect, then pushed on change.
  useResource(RESOURCES.miniBrowserActivity)
  const activity = useAppSelector(state => selectMiniBrowserActivity(state, sessionId))
  const running = activity?.status === 'starting' || activity?.status === 'ready'
  const browsing = running && !!activity?.browsing
  const [, setPanelMode] = usePersistedState(UI_STATE.chat.panelMode(sessionId))

  // The agent started browsing in the chat on screen: open its browser.
  const previous = useRef({ sessionId, browsing })
  useEffect(() => {
    const before = previous.current
    previous.current = { sessionId, browsing }
    if (enabled && before.sessionId === sessionId && !before.browsing && browsing) {
      setPanelMode('browser')
    }
  }, [enabled, sessionId, browsing, setPanelMode])

  // One panel per session: its live view, input and subscription are that
  // session's for their whole lifetime.
  const render = useCallback(
    () => <SessionBrowserPanel key={sessionId} sessionId={sessionId} />,
    [sessionId],
  )
  return useMemo(
    () => (enabled ? { running, browsing, render } : undefined),
    [enabled, running, browsing, render],
  )
}
