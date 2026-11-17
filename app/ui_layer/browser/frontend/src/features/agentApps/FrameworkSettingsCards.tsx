import { useEffect, useRef, useState, type Ref } from 'react'
import { Download, Loader2, Trash2 } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui/Button'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { usePersistedSet } from '../../hooks'
import { useAppSelector } from '../../store/hooks'
import { UI_STATE } from '../../store/uiState'
import { frameworkAppKey } from '../../store/slices/agentAppSlice'
import type { FrameworkRegistryApp } from '../../types'
import { frameworkKey } from './frameworkIdentity'
import { FrameworkAppActions, useFrameworkAppSettings } from './FrameworkAppActions'
import { FrameworkAppControls, FrameworkAppFeedback } from './FrameworkAppControls'
import { FrameworkAppDelete } from './FrameworkAppDialogs'
import { AppSettingsCard, AppSettingsInfo } from '../../pages/Settings/AgentAppSettingsCard'
import settingsStyles from '../../pages/Settings/SettingsPage.module.css'

function RegistrySettingsCard({ app, expanded, onToggle, onDelete, cardRef, stale, busy, operation }: {
  app: FrameworkRegistryApp; expanded: boolean; onToggle: () => void; onDelete: () => void; cardRef?: Ref<HTMLElement>; stale: boolean; busy: boolean; operation?: string
}) {
  const { t } = useTranslation(['settings', 'agentapp'])
  const settings = useFrameworkAppSettings(app.path, app.id, expanded && app.status !== 'missing', app.status, !!app.connection)
  const launching = busy && operation === 'start'
  const status = launching ? t('settings:agentApp.status.launching')
    : app.status === 'stopped' || (busy && operation === 'stop') ? t('settings:agentApp.status.notRunning')
    : t(`agentapp:registry.status.${app.status}`)
  const statusColor = launching ? 'var(--color-warning)'
    : busy && operation === 'stop' ? 'var(--text-muted)'
    : app.status === 'running' ? 'var(--color-success)' : app.status === 'unreachable' ? 'var(--color-error)' : 'var(--text-muted)'
  const exportApp = () => {
    if (!expanded) onToggle()
    void settings.manage('export')
  }
  return <AppSettingsCard name={app.name} status={stale ? t('agentapp:registry.lastKnown', { status }) : status}
    statusColor={statusColor} active={launching || (app.status === 'running' && !(busy && operation === 'stop'))} expanded={expanded} onToggle={onToggle} cardRef={cardRef}
    actions={<>
      <FrameworkAppControls app={app} compact />
      {!app.connection && <Button size="sm" variant="ghost" icon={settings.busy ? <Loader2 size={14} className={settingsStyles.spinning} /> : <Download size={14} />}
        title={t('settings:agentApp.exportProject')} disabled={stale || busy || settings.busy || app.status === 'missing'} onClick={exportApp} />}
      <Button size="sm" variant="ghost" icon={<Trash2 size={14} />} title={app.connection ? 'Disconnect app' : t('settings:agentApp.deleteProject')}
        aria-label={`${app.connection ? 'Disconnect' : 'Delete'} ${app.name}`} disabled={stale || busy || settings.busy} onClick={onDelete} />
    </>}>
    <AppSettingsInfo path={app.path} rows={app.connection ? [{ label: 'Account', value: app.connection.principalName || app.connection.principal }] : [
      { label: t('settings:agentApp.frontendPort'), value: settings.maintenance?.port ?? '—' },
      { label: t('settings:agentApp.backendPort'), value: settings.maintenance?.port ?? '—' },
      { label: t('settings:agentApp.projectId'), value: app.id },
    ]} />
    <FrameworkAppFeedback app={app} />
    {app.status !== 'missing' && <FrameworkAppActions app={app} settings={settings} />}
  </AppSettingsCard>
}

export function FrameworkSettingsCards() {
  const { t } = useTranslation(['agentapp', 'settings', 'common'])
  const location = useLocation()
  const { requestAgentAppList } = useWebSocket()
  const snapshot = useAppSelector(s => s.agentApp.framework)
  const connected = useAppSelector(s => s.connection.connected)
  const jobs = useAppSelector(s => s.agentApp.frameworkLifecycle)
  const [expanded, setExpanded, toggle] = usePersistedSet(UI_STATE.settings.agentAppExpandedProjects)
  const [deleting, setDeleting] = useState<FrameworkRegistryApp | null>(null)
  const selectedCard = useRef<HTMLElement | null>(null)
  const query = new URLSearchParams(location.search)
  const selectedKey = query.get('path') && query.get('id') ? frameworkKey(query.get('path')!, query.get('id')!) : null
  useEffect(() => { requestAgentAppList() }, [requestAgentAppList])
  useEffect(() => {
    if (selectedKey) setExpanded(previous => new Set(previous).add(selectedKey))
  }, [selectedKey, setExpanded])
  useEffect(() => { selectedCard.current?.scrollIntoView({ block: 'nearest' }) }, [selectedKey, snapshot.apps.length])
  const stale = !connected || snapshot.status !== 'success'
  return <>
    {(snapshot.status === 'loading' || snapshot.status === 'idle') && !snapshot.apps.length && <div className={settingsStyles.loadingState}>
      <Loader2 size={20} className={settingsStyles.spinning} />
      <span>{t('settings:agentApp.loadingProjects')}</span>
    </div>}
    {(!connected || snapshot.status === 'error' || snapshot.warning) && <p role="alert">
      {!connected ? t('registry.disconnected') : snapshot.status === 'error' ? t('registry.failed') : snapshot.warning}
    </p>}
    {snapshot.apps.map(app => {
      const key = frameworkKey(app.path, app.id)
      const open = expanded.has(key)
      const job = jobs[frameworkAppKey(app.path, app.id)]
      const busy = job?.status === 'running'
      return <RegistrySettingsCard key={key} app={app} expanded={open} onToggle={() => toggle(key)} onDelete={() => setDeleting(app)}
        stale={stale} busy={busy} operation={job?.operation} cardRef={key === selectedKey ? selectedCard : undefined} />
    })}
    {deleting && <FrameworkAppDelete app={deleting} onClose={() => setDeleting(null)} onDeleted={() => { setDeleting(null); requestAgentAppList() }} />}
  </>
}
