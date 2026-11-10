import { useEffect, useRef } from 'react'
import { usePersistedState } from '../../hooks'
import { useAppSelector } from '../../store/hooks'
import { RESOURCES, useResource } from '../../store/resources'
import { selectAgentAppCatalogLoaded } from '../../store/selectors/agentApp'
import { UI_STATE } from '../../store/uiState'
import type { AppsPanelMode } from '../../components/ChatWorkspace/ChatWorkspace'
import { FrameworkView } from '../../pages/AgentApp/FrameworkAppPage'
import { frameworkRequest, type FrameworkHostSnapshot } from './frameworkApi'
import { Box } from 'lucide-react'

import { frameworkKey } from './frameworkIdentity'

/**
 * The installed app a chat shows in its panel. Presentation only: showing an
 * app never references it for the agent, launches, stops or deletes it.
 */
export function usePanelApps(sessionId: string, enabled: boolean, visible = true): AppsPanelMode | undefined {
  useResource(enabled ? RESOURCES.agentAppsList : null)
  const loaded = useAppSelector(selectAgentAppCatalogLoaded)
  const registry = useAppSelector(s => s.agentApp.framework)
  const connected = useAppSelector(s => s.connection.connected)
  const [selectedId, setSelectedId] = usePersistedState(UI_STATE.chat.panelApp(sessionId))
  const resolve = (id: string) => registry.aliases?.[id] || id
  const selectedFramework = registry.apps.find(app => frameworkKey(app.path, app.id) === resolve(selectedId))
  const attachmentChecked = useRef('')
  useEffect(() => {
    if (!enabled || !connected || selectedId || registry.status !== 'success' || attachmentChecked.current === sessionId) return
    let active = true
    void frameworkRequest<FrameworkHostSnapshot>({ operation: 'snapshot' }).then(value => {
      const app = value.attachments.find(item => item.sessionId === sessionId)
      if (!active) return
      attachmentChecked.current = sessionId
      if (app && registry.apps.some(row => row.path === app.path && row.id === app.appId)) setSelectedId(frameworkKey(app.path, app.appId))
    }).catch(() => {})
    return () => { active = false }
  }, [sessionId, enabled, connected, selectedId, setSelectedId, registry.status, registry.apps])
  // Forget an app that is gone, but only on a catalog that actually arrived:
  // a failed or disconnected list says nothing about it.
  useEffect(() => {
    if (enabled && registry.aliases?.[selectedId]) { setSelectedId(registry.aliases[selectedId]); return }
    if (enabled && loaded && registry.status === 'success' && selectedId && !selectedId.startsWith('framework:')) setSelectedId('')
    if (enabled && registry.status === 'success' && selectedId.startsWith('framework:') && !selectedFramework) setSelectedId('')
  }, [enabled, loaded, registry.status, registry.aliases, selectedId, selectedFramework, setSelectedId])
  if (!enabled) return undefined
  const canOpenProject = (id: string) => registry.apps.some(app => frameworkKey(app.path, app.id) === resolve(id))
  return {
    choices: registry.apps.map(app => ({ id: frameworkKey(app.path, app.id), title: app.name, icon: <Box size={14} /> })),
    loaded,
    selected: selectedFramework ? { id: selectedId, title: selectedFramework.name, icon: <Box size={16} /> } : null,
    select: id => { if (canOpenProject(id)) setSelectedId(resolve(id)) },
    clear: () => { attachmentChecked.current = sessionId; setSelectedId('') },
    canOpenProject,
    render: (projectId, moving, interactive) => {
      const app = registry.apps.find(item => frameworkKey(item.path, item.id) === resolve(projectId))
      if (app) return <FrameworkView key={projectId} path={app.path} appId={app.id} panel blocked={!interactive || moving || !visible} />
      return null
    },
  }
}
