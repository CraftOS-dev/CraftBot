import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'
import { CraftBotMascot } from '@mascot'
import { Button } from '../../components/ui/Button'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { getSocketClient } from '../../store/socket/socketInstance'
import { cancelFrameworkOpen, frameworkAppKey, invalidateFrameworkView, receiveFrameworkAttachment, receiveFrameworkOpen, requestFrameworkOpen } from '../../store/slices/agentAppSlice'
import { FrameworkAppControls } from '../../features/agentApps/FrameworkAppControls'
import { FrameworkRequestFeedback, useFrameworkRequests } from '../../features/agentApps/FrameworkRequestFeedback'
import { frameUrl, frameworkFrameId, removeIframe } from '../../features/agentApps/frameHost'
import { usePersistentAppFrame } from '../../features/agentApps/useAgentAppFrame'
import { frameworkRequest, type FrameworkAttachment } from '../../features/agentApps/frameworkApi'
import { AgentAppWorkspace } from './AgentAppWorkspace'
import { ConstructionDock } from './ConstructionDock'
import { frameworkSessionIdentity } from '../../features/agentApps/frameworkIdentity'
import type { AgentAppBuildEvent, FrameworkAppView } from '../../types'
import surface from '../../features/agentApps/AgentAppSurface.module.css'
import styles from './FrameworkAppPage.module.css'

const errors = {
  stopped: 'registry.view.stopped', missing: 'registry.view.missing', unreachable: 'registry.view.unreachable',
  not_registered: 'registry.view.notRegistered', identity_changed: 'registry.view.identityChanged',
  separate_view: 'registry.view.separateView', query_failed: 'registry.view.failed',
} as const
const NO_BUILD_EVENTS: AgentAppBuildEvent[] = []

function usableFrameUrl(value: string): string | null {
  try {
    const url = new URL(frameUrl(value))
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname)
      || url.username || url.password || url.origin === window.location.origin) return null
    return url.toString()
  } catch { return null }
}

/** Presentation only; lifecycle and app styling remain with Agent-App. */
function FrameworkFrame({ id, url, name, blocked, moving, retry }: { id: string; url: string; name: string; blocked: boolean; moving: boolean; retry: () => void }) {
  const { t } = useTranslation('agentapp')
  const frame = usePersistentAppFrame({ id, url, name, status: 'running' }, true, moving, blocked)
  const loaded = frame.status === 'ready', failed = frame.status === 'timeout' || frame.status === 'unavailable'
  return <div className={surface.view}>
    <div ref={frame.placeholder} className={surface.placeholder} />
    {!loaded && <div className={surface.notice} role="status">
      {failed ? <><AlertCircle size={18} /><span>{t('registry.view.frameFailed')}</span>
        <Button variant="secondary" onClick={retry}>{t('registry.view.retry')}</Button></>
        : <><Loader2 size={18} /><span>{t('registry.view.loading')}</span></>}
    </div>}
  </div>
}

export function FrameworkView({ path, appId, blocked = false, moving = false }: { path: string; appId: string; panel?: boolean; blocked?: boolean; moving?: boolean }) {
  const { t } = useTranslation('agentapp')
  const dispatch = useAppDispatch()
  const connected = useAppSelector(state => state.connection.connected)
  const request = useRef<string | null>(null)
  const response = useAppSelector(state => state.agentApp.frameworkViews[request.current || ''] || state.agentApp.frameworkView)
  const app = useAppSelector(state => state.agentApp.framework.apps.find(item => item.path === path && item.id === appId))
  const job = useAppSelector(state => state.agentApp.frameworkLifecycle[frameworkAppKey(path, appId)])
  const busy = job?.status === 'running'
  const requests = useFrameworkRequests(path, appId, connected && app?.status === 'running' && !busy)
  const [attempt, setAttempt] = useState(0)
  const [frameAttempt, setFrameAttempt] = useState(0)
  const cachedView = useAppSelector(state => state.agentApp.frameworkResolvedViews[frameworkAppKey(path, appId)])
  const lastView = useRef<FrameworkAppView | null>(null)
  if (cachedView) lastView.current = cachedView
  const view = cachedView || (!connected ? lastView.current : null)

  useEffect(() => {
    if (busy || cachedView) return
    if (!connected || !path || !appId) return
    const requestId = crypto.randomUUID()
    request.current = requestId
    // Defer dispatch/send together so StrictMode's discarded mount sends nothing.
    const send = window.setTimeout(() => {
      dispatch(requestFrameworkOpen({ requestId, path, appId }))
      getSocketClient().send('agent_app_framework_open', { requestId, path, appId })
    }, 0)
    const timeout = window.setTimeout(() => dispatch(receiveFrameworkOpen({
      requestId, status: 'error', code: 'query_failed', message: '',
    })), 50_000)
    return () => {
      clearTimeout(send)
      clearTimeout(timeout)
      request.current = null
      dispatch(cancelFrameworkOpen(requestId))
    }
  }, [appId, path, connected, attempt, dispatch, busy, job?.requestId, job?.status, cachedView])

  useEffect(() => {
    if (response.requestId !== request.current || response.status === 'loading') return
    if (response.status === 'error') { removeIframe(frameworkFrameId(path, appId)); lastView.current = null }
  }, [response, path, appId])

  const current = response.requestId !== null && response.requestId === request.current
  const code = !path || !appId ? 'not_registered' : current && response.status === 'error' ? response.code : null
  const url = view ? usableFrameUrl(view.url) : null
  const invalid = view !== null && url === null
  const message = invalid ? t('registry.view.unreachable')
    : code ? t(errors[code as keyof typeof errors] || 'registry.view.failed') : null
  const name = view?.name || app?.name || t('registry.view.title')
  const retry = () => { removeIframe(frameworkFrameId(path, appId)); lastView.current = null; dispatch(invalidateFrameworkView({ path, appId })); setFrameAttempt(value => value + 1); setAttempt(value => value + 1) }

  return <section className={surface.surface} aria-label={t('registry.view.title')} style={blocked ? { pointerEvents: 'none' } : undefined}>
    <FrameworkRequestFeedback name={name} state={requests} />
    {view && !connected && <div className={styles.connectionNotice} role="status">{t('registry.disconnected')}</div>}
    {url && !message ? <FrameworkFrame key={`${url}:${frameAttempt}`} id={frameworkFrameId(path, appId)} url={url} name={name} blocked={blocked || requests.open} moving={moving} retry={retry} />
      : <div className={surface.state} role={message ? 'alert' : 'status'}>
        {busy && job.operation === 'start' ? <CraftBotMascot state="launching" size={96} />
          : code === 'stopped' ? <CraftBotMascot state="stopped" size={96} />
          : message ? <AlertCircle size={28} /> : connected ? <Loader2 size={28} className={surface.spinner} /> : null}
        <p title={current ? response.message || undefined : undefined}>
          {busy ? t(job.operation === 'start' ? 'registry.lifecycle.starting' : 'registry.lifecycle.stopping')
            : message || (!connected ? t('registry.disconnected') : t('registry.view.checking'))}
        </p>
        {app && <FrameworkAppControls app={app} />}
        {message && <Button variant="secondary" disabled={!connected || busy} onClick={retry}><RefreshCw size={14} />{t('registry.view.retry')}</Button>}
      </div>}
  </section>
}

export function FrameworkAppPage() {
  const [params] = useSearchParams()
  const path = params.get('path') || '', appId = params.get('id') || ''
  return <FrameworkWorkspace key={JSON.stringify([path, appId])} path={path} appId={appId} />
}

/** Creation already owns its conversation, before the registry knows the app. */
export function FrameworkSessionPage({ sessionId }: { sessionId: string }) {
  const session = useAppSelector(state => state.sessions.sessions.find(item => item.id === sessionId))
  const identity = frameworkSessionIdentity(session?.agentAppFrameworkKey)
  return <FrameworkWorkspace key={sessionId} path={identity?.path || ''} appId={identity?.appId || ''} knownSessionId={sessionId} />
}

function FrameworkWorkspace({ path, appId, knownSessionId }: { path: string; appId: string; knownSessionId?: string }) {
  const { t } = useTranslation('agentapp')
  const dispatch = useAppDispatch()
  const connected = useAppSelector(state => state.connection.connected)
  const attachedSessionId = useAppSelector(state => state.agentApp.frameworkSessions[frameworkAppKey(path, appId)])
  const requestedSessionId = knownSessionId || attachedSessionId
  const session = useAppSelector(state => state.sessions.sessions.find(item => {
    if (requestedSessionId) return item.id === requestedSessionId
    const identity = frameworkSessionIdentity(item.agentAppFrameworkKey)
    return identity?.path === path && identity?.appId === appId
  }))
  const sessionId = requestedSessionId || session?.id
  const app = useAppSelector(state => state.agentApp.framework.apps.find(item => item.path === path && item.id === appId))
  const todos = useAppSelector(state => state.agentApp.todos[`framework-build:${sessionId}`]) ?? session?.agentAppBuild?.todos
  const building = session?.agentAppFrameworkPending || session?.agentAppBuild?.building
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (knownSessionId || attachedSessionId || !connected || !path || !appId) return
    let active = true
    // Reuse the host's app conversation. Attaching does not start an agent turn
    // or grant permission for app-initiated tasks. Defer for StrictMode cleanup.
    const timer = window.setTimeout(() => {
      setError('')
      void frameworkRequest<FrameworkAttachment>({ operation: 'attach', path, appId }).then(value => {
        if (!active) return
        if (value.path !== path || value.appId !== appId || !value.sessionId) throw new Error(t('registry.view.chatFailed'))
        dispatch(receiveFrameworkAttachment(value))
      }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : String(reason)) })
    }, 0)
    return () => { active = false; window.clearTimeout(timer) }
  }, [path, appId, knownSessionId, attachedSessionId, connected, attempt, t, dispatch])

  const fallback = path && appId ? <div className={surface.state} role={error ? 'alert' : 'status'}>
    <p>{error ? t('registry.view.chatFailed') : t(connected ? 'registry.view.chatLoading' : 'registry.disconnected')}</p>
    {error && <><p>{error}</p><Button variant="secondary" disabled={!connected} onClick={() => setAttempt(value => value + 1)}>{t('registry.view.retry')}</Button></>}
  </div> : undefined
  return <AgentAppWorkspace sessionId={sessionId} chatFallback={fallback}>
    {moving => building ? <ConstructionDock project={{ name: app?.name || session?.title || t('registry.view.title'), status: 'creating' }}
      todos={todos} events={NO_BUILD_EVENTS} snapshot={null}
      activity={session?.agentAppBuild?.verifying ? t('registry.view.verifying') : undefined} />
      : <FrameworkView path={path} appId={appId} moving={moving} />}
  </AgentAppWorkspace>
}
