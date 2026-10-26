import { useCallback, useEffect } from 'react'
import { usePersistedState } from '../../hooks'
import { useAppSelector } from '../../store/hooks'
import { RESOURCES, useResource } from '../../store/resources'
import { selectAgentAppCatalogLoaded, selectAgentAppProjects } from '../../store/selectors/agentApp'
import { UI_STATE } from '../../store/uiState'
import { attachPanelApp, retainPanelApps } from './panelAppsState'
import { AgentAppSurface } from './AgentAppSurface'
import { AgentAppIcon } from '../../components/ui/AgentAppIcon'
import { IconButton } from '../../components/ui/IconButton'
import { ArrowUpRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

/** Per-chat presentation state; attaching an app does not reference it for the agent. */
export function usePanelApps(sessionId: string, enabled: boolean, excludedId?: string, visible = true) {
  const { t } = useTranslation('chat')
  const navigate = useNavigate()
  useResource(enabled ? RESOURCES.agentAppsList : null)
  const projects = useAppSelector(selectAgentAppProjects)
  const loaded = useAppSelector(selectAgentAppCatalogLoaded)
  const [state, setState] = usePersistedState(UI_STATE.chat.panelApps(sessionId))
  useEffect(() => {
    if (!loaded || !enabled) return
    const ids = new Set(projects.filter(p => p.id !== excludedId).map(p => p.id))
    const next = retainPanelApps(state, id => ids.has(id))
    if (next !== state) setState(next)
  }, [loaded, enabled, projects, excludedId, state, setState])
  const openProject = useCallback((id: string) => {
    if (id !== excludedId && projects.some(project => project.id === id)) setState(previous => attachPanelApp(previous, id))
  }, [excludedId, projects, setState])
  const eligible = projects.filter(p => p.id !== excludedId)
  const attached = state.projectIds.flatMap(id => eligible.find(p => p.id === id) ?? [])
  const selected = attached.find(p => p.id === state.selectedProjectId) ?? attached[0]
  return enabled ? {
    openProject,
    canOpenProject: (id: string) => id !== excludedId && projects.some(p => p.id === id),
    tabs: attached.map(project => ({ id: `app:${project.id}`, title: project.name,
      icon: <AgentAppIcon projectId={project.id} icon={project.icon} size={13} />,
      closeLabel: t('apps.remove', { name: project.name }) })),
    selectedId: selected ? `app:${selected.id}` : null,
    removeProject: (id: string) => setState(previous => retainPanelApps(previous, key => key !== id)),
    loaded,
    choices: eligible.map(project => ({ id: project.id, title: project.name, icon: <AgentAppIcon projectId={project.id} icon={project.icon} size={19} /> })),
    actions: selected && <IconButton type="button" size="sm" icon={<ArrowUpRight size={17} />} onClick={() => navigate(`/agent-app/${encodeURIComponent(selected.id)}`)} aria-label={t('apps.openFull')} tooltip={t('apps.openFull')} />,
    render: (moving: boolean, active: boolean) => selected
      ? <AgentAppSurface key={selected.id} project={selected} active={active && visible} moving={moving}  />
      : null,
  } : undefined
}
