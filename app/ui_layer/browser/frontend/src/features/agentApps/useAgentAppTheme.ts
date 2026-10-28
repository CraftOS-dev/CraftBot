import { useEffect, useState } from 'react'
import { useTheme } from '../../contexts/ThemeContext'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { DEFAULT_CUSTOM_COLORS } from '../../pages/AgentApp/AgentAppThemeModal'
import type { AgentAppThemeId, AgentAppCustomColors } from '../../pages/AgentApp/AgentAppThemeModal'
import type { AgentAppProject } from '../../types'
import { acceptsFrameMessage, postMessageToIframe } from './frameHost'

function loadAgentAppTheme(projectId: string): AgentAppThemeId {
  try {
    const stored = localStorage.getItem(`agentapp-theme-${projectId}`)
    if (stored) return stored as AgentAppThemeId
  } catch {}
  return 'craftbot'
}

function saveAgentAppTheme(projectId: string, themeId: AgentAppThemeId) {
  try { localStorage.setItem(`agentapp-theme-${projectId}`, themeId) } catch {}
}

function loadAgentAppCustomColors(projectId: string): AgentAppCustomColors {
  try {
    const raw = localStorage.getItem(`agentapp-custom-colors-${projectId}`)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed.bg && parsed.surface && parsed.text && parsed.accent) return parsed
    }
  } catch {}
  return { ...DEFAULT_CUSTOM_COLORS }
}

function saveAgentAppCustomColors(projectId: string, colors: AgentAppCustomColors) {
  try { localStorage.setItem(`agentapp-custom-colors-${projectId}`, JSON.stringify(colors)) } catch {}
}

export function useAgentAppTheme(project: AgentAppProject | undefined) {
  const projectId = project?.id
  const { theme: appTheme } = useTheme()
  const { updateAgentAppTheme } = useWebSocket()
  const [agentAppTheme, setAgentAppTheme] = useState<AgentAppThemeId>(
    () => (projectId ? loadAgentAppTheme(projectId) : 'craftbot')
  )
  const [agentAppCustomColors, setAgentAppCustomColors] = useState<AgentAppCustomColors>(
    () => (projectId ? loadAgentAppCustomColors(projectId) : { ...DEFAULT_CUSTOM_COLORS })
  )
  // The server-persisted theme is authoritative: a pick made in any tab or
  // browser (or by the wizard) reaches this page when the project list
  // refetches. localStorage only paints the first frame before the list
  // arrives. Legacy projects with no saved theme fall back to the
  // scaffold-time stylePack unless the user picked one locally.
  useEffect(() => {
    if (!projectId) return
    setAgentAppTheme(loadAgentAppTheme(projectId))
    setAgentAppCustomColors(loadAgentAppCustomColors(projectId))
    try {
      const saved = project?.uiTheme
      if (saved?.themeId) {
        const themeId = saved.themeId as AgentAppThemeId
        setAgentAppTheme(themeId)
        saveAgentAppTheme(projectId, themeId)
        const colors = saved.customColors
        if (themeId === 'custom' && colors?.bg && colors?.surface && colors?.text && colors?.accent) {
          const custom = { bg: colors.bg, surface: colors.surface, text: colors.text, accent: colors.accent }
          setAgentAppCustomColors(custom)
          saveAgentAppCustomColors(projectId, custom)
        }
        return
      }
      if (localStorage.getItem(`agentapp-theme-${projectId}`)) return
      const stylePack = project?.stylePack
      if (stylePack && stylePack !== 'craftbot') setAgentAppTheme(stylePack as AgentAppThemeId)
    } catch { /* cosmetic only */ }
  }, [projectId, project?.uiTheme, project?.stylePack])

  // Send the selected Agent App theme + current app mode to the iframe.
  // NOTE: the postMessage `type` stays 'livingui-theme' — it is the wire
  // contract with apps already built by their bridge. Renaming it (like the
  // rest of the Living UI → Agent App rename) would silently break theme
  // following for every app scaffolded before the rename, so it's kept stable
  // exactly like the other retained runtime values (trigger/session values).
  useEffect(() => {
    if (!projectId || project?.status !== 'running') return
    postMessageToIframe(projectId, {
      type: 'livingui-theme',
      themeId: agentAppTheme,
      mode: appTheme,
      // Only for the 'custom' theme — the bridge applies these as inline
      // overrides that outrank every style-pack rule.
      customColors: agentAppTheme === 'custom' ? agentAppCustomColors : undefined,
    })
  }, [agentAppTheme, agentAppCustomColors, appTheme, projectId, project?.status])

  // When the iframe finishes loading it sends 'craftbot-theme-request'. Reply
  // with the saved per-project theme so the palette persists across refreshes.
  useEffect(() => {
    if (!projectId) return
    const onIframeReady = (e: MessageEvent) => {
      if (e.data?.type !== 'craftbot-theme-request' || !e.source) return
      if (!acceptsFrameMessage(projectId, e)) return
      postMessageToIframe(projectId, {
        // Stable wire type — see the send effect above.
        type: 'livingui-theme',
        themeId: agentAppTheme,
        mode: appTheme,
        customColors: agentAppTheme === 'custom' ? agentAppCustomColors : undefined,
      })
    }
    window.addEventListener('message', onIframeReady)
    return () => window.removeEventListener('message', onIframeReady)
  }, [projectId, agentAppTheme, agentAppCustomColors, appTheme])

  const handleThemeSelect = (themeId: AgentAppThemeId, colors?: AgentAppCustomColors) => {
    if (!projectId) return
    setAgentAppTheme(themeId)
    saveAgentAppTheme(projectId, themeId)
    if (colors) {
      setAgentAppCustomColors(colors)
      saveAgentAppCustomColors(projectId, colors)
    }
    // Server-side persistence so the pick follows the user across browsers.
    updateAgentAppTheme(projectId, {
      themeId,
      ...(themeId === 'custom' ? { customColors: colors ?? agentAppCustomColors } : {}),
    })
  }

  return { agentAppTheme, agentAppCustomColors, handleThemeSelect }
}
