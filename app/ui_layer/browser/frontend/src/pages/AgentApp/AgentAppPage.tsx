import { Navigate, useParams } from 'react-router-dom'
import { useAppSelector } from '../../store/hooks'
import { frameworkKey } from '../../features/agentApps/frameworkIdentity'

/** Retain bookmarks for apps that were already migrated to the registry. */
export function AgentAppPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const alias = useAppSelector(state => state.agentApp.framework.aliases[projectId || ''])
  const loaded = useAppSelector(state => state.agentApp.framework.hasSnapshot)
  const app = useAppSelector(state => state.agentApp.framework.apps.find(row => frameworkKey(row.path, row.id) === alias))
  if (!loaded) return null
  return <Navigate replace to={app ? `/framework-app?${new URLSearchParams({ path: app.path, id: app.id })}` : '/settings?tab=agent_app'} />
}
