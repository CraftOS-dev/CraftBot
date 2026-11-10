import { Loader2, Play, Square } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { getSocketClient } from '../../store/socket/socketInstance'
import { frameworkAppKey, receiveFrameworkLifecycle } from '../../store/slices/agentAppSlice'
import type { FrameworkRegistryApp } from '../../types'
import { Button } from '../../components/ui/Button'
import navStyles from '../../components/layout/NavBar.module.css'
import styles from './FrameworkAppList.module.css'

export function FrameworkAppControls({ app, menu = false, compact = false }: { app: FrameworkRegistryApp; menu?: boolean; compact?: boolean }) {
  const { t } = useTranslation(['agentapp', 'settings'])
  const dispatch = useAppDispatch()
  const connected = useAppSelector(state => state.connection.connected)
  const fresh = useAppSelector(state => state.agentApp.framework.status === 'success')
  const job = useAppSelector(state => state.agentApp.frameworkLifecycle[frameworkAppKey(app.path, app.id)])
  const busy = job?.status === 'running'
  const operation = busy ? job.operation : app.status === 'running' ? 'stop' : 'start'
  const supported = app.status === 'running' || app.status === 'stopped'
  const act = () => {
    if (!connected || !fresh || busy || !supported) return
    const request = { requestId: crypto.randomUUID(), path: app.path, appId: app.id, operation }
    dispatch(receiveFrameworkLifecycle({ ...request, status: 'running' }))
    if (!getSocketClient().sendNow('agent_app_framework_lifecycle', request)) {
      dispatch(receiveFrameworkLifecycle({ ...request, status: 'unknown' }))
    }
  }
  const label = t(busy ? operation === 'start' ? 'registry.lifecycle.starting' : 'registry.lifecycle.stopping'
    : operation === 'start' ? 'registry.lifecycle.start' : 'registry.lifecycle.stop')
  const props = {
    disabled: !connected || !fresh || busy,
    onClick: act,
    'aria-label': t(operation === 'start' ? 'registry.lifecycle.startApp' : 'registry.lifecycle.stopApp', { name: app.name }),
    title: t(operation === 'start' ? 'registry.lifecycle.startHint' : 'registry.lifecycle.stopHint'),
  }
  const iconSize = menu ? 13 : compact ? 14 : 16
  const icon = busy ? <Loader2 size={iconSize} className={styles.spinner} />
    : operation === 'start' ? <Play size={iconSize} /> : <Square size={iconSize} />
  if (menu) return supported && <button className={navStyles.sessionMenuItem} {...props}>{icon}{label}</button>
  if (compact) return supported && <Button {...props} size="sm" variant={operation === 'stop' ? 'danger' : 'primary'} icon={icon}>{!busy && operation === 'start' ? t('settings:agentApp.launch') : label}</Button>
  return <div className={styles.controls}>
    {supported && <Button {...props} icon={icon}>{label}</Button>}
    <FrameworkAppFeedback app={app} />
  </div>
}

export function FrameworkAppFeedback({ app }: { app: FrameworkRegistryApp }) {
  const { t } = useTranslation('agentapp')
  const job = useAppSelector(state => state.agentApp.frameworkLifecycle[frameworkAppKey(app.path, app.id)])
  const busy = job?.status === 'running'
  return <>
    {busy && job.message && <p className={styles.feedback} role="status">{job.message}</p>}
    {job?.status === 'error' && <p className={styles.feedback} role="alert">{job.message || t('registry.lifecycle.failed')}</p>}
    {job?.status === 'unknown' && <p className={styles.feedback} role="status">{t('registry.lifecycle.unknown')}</p>}
    {job?.remaining && job.operation === 'stop' && job.status !== 'running' && <p className={styles.feedback} role="status">{t('registry.lifecycle.remaining')}</p>}
  </>
}
