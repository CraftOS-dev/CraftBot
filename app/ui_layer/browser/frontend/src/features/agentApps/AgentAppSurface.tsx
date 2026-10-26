import { AlertCircle, Loader2, Play, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { CraftBotMascot } from '@mascot'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useAppSelector } from '../../store/hooks'
import { selectConnected } from '../../store/selectors/connection'
import { selectAgentAppBuildEvents, selectAgentAppSnapshots, selectAgentAppTodos } from '../../store/selectors/agentApp'
import { Button } from '../../components/ui/Button'
import { ConstructionDock } from '../../pages/AgentApp/ConstructionDock'
import type { AgentAppBuildEvent, AgentAppProject } from '../../types'
import { useAgentAppFrame } from './useAgentAppFrame'
import { useAgentAppTheme } from './useAgentAppTheme'
import styles from './AgentAppSurface.module.css'

const EMPTY_EVENTS: AgentAppBuildEvent[] = []

function ThemeBridge({ project }: { project: AgentAppProject }) {
  useAgentAppTheme(project)
  return null
}

/** App content only. Navigation, backing chats and process management stay outside. */
export function AgentAppSurface({ project, active = true, moving = false, blocked = false, themeManaged = false, onDelete }: {
  project: AgentAppProject
  active?: boolean
  moving?: boolean
  blocked?: boolean
  themeManaged?: boolean
  onDelete?: () => void
}) {
  const { t } = useTranslation(['agentapp', 'chat', 'common'])
  const { launchAgentApp } = useWebSocket()
  const connected = useAppSelector(selectConnected)
  const todos = useAppSelector(selectAgentAppTodos)[project.id]
  const events = useAppSelector(selectAgentAppBuildEvents)[project.id] ?? EMPTY_EVENTS
  const snapshot = useAppSelector(selectAgentAppSnapshots)[project.id] ?? null
  const frame = useAgentAppFrame(project, active, moving, blocked)
  const busy = project.status === 'launching' || project.status === 'stopping'
  return <div className={styles.surface}>
    {!themeManaged && <ThemeBridge key={project.id} project={project} />}
    {project.status === 'running' && project.url ? <>
      <div ref={frame.placeholder} className={styles.placeholder} />
      {frame.status !== 'ready' && <div className={styles.notice} role="status">
        {frame.status === 'loading' ? <><Loader2 size={18} /><span>{t('chat:apps.loadingView')}</span></>
          : <><AlertCircle size={18} /><span>{t(frame.status === 'timeout' ? 'chat:apps.viewTimeout' : 'chat:apps.viewUnavailable')}</span>
            <Button variant="secondary" onClick={frame.retry}><RefreshCw size={14} />{t('chat:apps.retry')}</Button></>}
      </div>}
    </> : project.status === 'creating' ? <ConstructionDock project={project} todos={todos} events={events} snapshot={snapshot} />
      : <div className={styles.state} role="status">
        {busy ? <Loader2 size={32} className={styles.spinner} /> : project.status === 'error' ? <AlertCircle size={32} /> : <CraftBotMascot state="stopped" size={96} />}
        <p>{t(`agentapp:page.${project.status === 'launching' ? 'launchingTitle' : project.status === 'stopping' ? 'stoppingTitle' : project.status === 'error' ? 'errorTitle' : 'stoppedTitle'}`)}</p>
        {project.error && <p className={styles.error}>{project.error}</p>}
        {!busy && <Button variant="primary" disabled={!connected} onClick={() => launchAgentApp(project.id)}><Play size={16} />{t('agentapp:page.launch')}</Button>}
        {project.status === 'error' && onDelete && <Button variant="secondary" onClick={onDelete}>{t('agentapp:page.deleteProject')}</Button>}
        {!connected && <p>{t('chat:apps.disconnected')}</p>}
      </div>}
  </div>
}
