import { useEffect } from 'react'
import { usePersistedState } from '../../hooks'
import { useAppSelector } from '../../store/hooks'
import { RESOURCES, useResource } from '../../store/resources'
import { selectAgentAppCatalogLoaded, selectAgentAppProjects } from '../../store/selectors/agentApp'
import { UI_STATE } from '../../store/uiState'
import { AgentAppIcon } from '../../components/ui/AgentAppIcon'
import type { AppsPanelMode } from '../../components/ChatWorkspace/ChatWorkspace'
import { AgentAppSurface } from './AgentAppSurface'

/**
 * The installed app a chat shows in its panel. Presentation only: showing an
 * app never references it for the agent, launches, stops or deletes it.
 */
export function usePanelApps(sessionId: string, enabled: boolean, visible = true): AppsPanelMode | undefined {
  useResource(enabled ? RESOURCES.agentAppsList : null)
  const projects = useAppSelector(selectAgentAppProjects)
  const loaded = useAppSelector(selectAgentAppCatalogLoaded)
  const [selectedId, setSelectedId] = usePersistedState(UI_STATE.chat.panelApp(sessionId))
  const selected = projects.find(project => project.id === selectedId)
  // Forget an app that is gone, but only on a catalog that actually arrived:
  // a failed or disconnected list says nothing about it.
  useEffect(() => {
    if (enabled && loaded && selectedId && !selected) setSelectedId('')
  }, [enabled, loaded, selectedId, selected, setSelectedId])
  if (!enabled) return undefined
  const canOpenProject = (id: string) => projects.some(project => project.id === id)
  return {
    choices: projects.map(project => ({
      id: project.id, title: project.name, icon: <AgentAppIcon projectId={project.id} icon={project.icon} size={14} />,
    })),
    loaded,
    selected: selected
      ? { id: selected.id, title: selected.name, icon: <AgentAppIcon projectId={selected.id} icon={selected.icon} size={16} /> }
      : null,
    select: id => { if (canOpenProject(id)) setSelectedId(id) },
    clear: () => setSelectedId(''),
    canOpenProject,
    render: (projectId, moving, interactive) => {
      const project = projects.find(item => item.id === projectId)
      return project
        ? <AgentAppSurface key={project.id} project={project} active={visible} moving={moving} blocked={!interactive} />
        : null
    },
  }
}
