import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate } from 'react-router-dom'
import {
  AlertCircle,
} from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useAgentAppTheme } from '../../features/agentApps/useAgentAppTheme'
import { AgentAppSurface } from '../../features/agentApps/AgentAppSurface'
import { Button } from '../../components/ui/Button'
import { ConfirmModal } from '../../components/ui/ConfirmModal'
import { AgentAppWorkspace } from './AgentAppWorkspace'
import { removeIframe } from '../../features/agentApps/frameHost'
import { AgentAppThemeModal } from './AgentAppThemeModal'
import { useAppSelector } from '../../store/hooks'
import { frameworkRoute } from '../../features/agentApps/frameworkIdentity'
import {
  selectAgentAppProjects,
} from '../../store/selectors/agentApp'
import styles from './AgentAppPage.module.css'

export function AgentAppPage() {
  const { t } = useTranslation(['agentapp', 'common'])
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const {
    deleteAgentApp,
    setActiveAgentApp,
  } = useWebSocket()
  const agentAppProjects = useAppSelector(selectAgentAppProjects)
  const migrated = useAppSelector(s => projectId ? s.agentApp.framework.aliases[projectId] : undefined)
  useEffect(() => {
    if (migrated?.startsWith('framework:')) {
      try {
        const [path, id] = JSON.parse(migrated.slice('framework:'.length)) as [string, string]
        navigate(frameworkRoute(path, id), { replace: true })
      } catch { /* An invalid alias cannot choose another app. */ }
    }
  }, [migrated, navigate])

  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showThemeModal, setShowThemeModal] = useState(false)
  // The theme picker now lives behind the sidebar row's "…" menu. That kebab
  // only appears for the active project, so its page (this one) is mounted and
  // catches the event to open the modal here, where the iframe bridge lives.
  useEffect(() => {
    if (!projectId) return
    const onOpenTheme = (e: Event) => {
      const detail = (e as CustomEvent<{ projectId?: string }>).detail
      if (detail?.projectId === projectId) setShowThemeModal(true)
    }
    window.addEventListener('agentapp:open-theme', onOpenTheme)
    return () => window.removeEventListener('agentapp:open-theme', onOpenTheme)
  }, [projectId])

  // Find the current project
  const project = agentAppProjects.find(p => p.id === projectId)
  const { agentAppTheme, agentAppCustomColors, handleThemeSelect } = useAgentAppTheme(project)

  // Set active Agent App when viewing
  useEffect(() => {
    if (projectId) {
      setActiveAgentApp(projectId)
    }
    return () => {
      setActiveAgentApp(null)
    }
  }, [projectId, setActiveAgentApp])

  const handleDelete = () => {
    if (projectId) {
      removeIframe(projectId)
      deleteAgentApp(projectId)
      navigate('/')
    }
  }

  // Project not found
  if (!project) {
    return (
      <div className={styles.notFound}>
        <AlertCircle size={48} />
        <h2>{t('agentapp:page.notFoundTitle')}</h2>
        <p>{t('agentapp:page.notFoundBody')}</p>
        <Button variant="primary" onClick={() => navigate('/')}>
          {t('agentapp:page.goToChat')}
        </Button>
      </div>
    )
  }

  return (
    <>
      <AgentAppWorkspace sessionId={project.sessionId}>
        {moving => <AgentAppSurface project={project} moving={moving}
          blocked={showThemeModal || showDeleteModal} onDelete={() => setShowDeleteModal(true)}
          themeManaged />}
      </AgentAppWorkspace>

      {/* Theme Picker Modal */}
      <AgentAppThemeModal
        isOpen={showThemeModal}
        activeTheme={agentAppTheme}
        customColors={agentAppCustomColors}
        onSelect={handleThemeSelect}
        onClose={() => setShowThemeModal(false)}
      />

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={showDeleteModal}
        title={t('agentapp:page.deleteModalTitle')}
        message={t('agentapp:page.deleteModalMessage', { name: project.name })}
        confirmText={t('common:actions.delete')}
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
      />
    </>
  )
}
