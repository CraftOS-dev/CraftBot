import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useToast } from '../../contexts/ToastContext'
import { useAppSelector } from '../../store/hooks'
import { frameworkRequest, type FrameworkHostSnapshot, type FrameworkInstallJob } from './frameworkApi'
import { frameworkRoute } from './frameworkIdentity'

/** Bind CraftBot's existing creation dialog to the upstream host, without legacy scaffolding. */
export function useFrameworkCreation(onClose: () => void) {
  const navigate = useNavigate()
  const { requestAgentAppList } = useWebSocket()
  const { showToast } = useToast()
  const connected = useAppSelector(s => s.connection.connected)
  const [pending, setPending] = useState<string[]>([])
  const reported = useRef(new Set<string>())
  useEffect(() => {
    if (!connected || !pending.length) return
    let active = true, timer: number
    const refresh = async () => {
      try {
        const snapshot = await frameworkRequest<FrameworkHostSnapshot>({ operation: 'snapshot' })
        if (!active) return
        for (const job of snapshot.jobs.filter(job => pending.includes(job.id))) {
          const done = job.status !== 'running'
          if (done && reported.current.has(job.id)) continue
          const problem = job.error || job.linkError || job.steps.find(step => step.error)?.error
          const installed = job.status === 'success' && !problem
          const appRoute = job.result?.dir && job.result?.id ? frameworkRoute(job.result.dir, job.result.id) : null
          showToast(job.status === 'running' ? 'info' : job.status === 'success' && !problem ? 'success' : 'error',
            job.status === 'running' ? 'Installing app…' : installed ? 'App installed' : 'App installation needs attention', undefined, {
              key: `framework-install:${job.id}`, sticky: !done,
              detail: problem,
              actions: installed && appRoute ? [{ label: 'Open app', onClick: () => navigate(appRoute) }] : undefined,
            })
          if (done) {
            reported.current.add(job.id)
            setPending(ids => ids.filter(id => id !== job.id))
            requestAgentAppList()
          }
        }
      } catch (error) {
        if (active) showToast('error', 'Could not check installation progress', undefined, { key: 'framework-install-refresh', detail: String(error) })
      }
      if (active) timer = window.setTimeout(refresh, 2500)
    }
    void refresh()
    return () => { active = false; clearTimeout(timer) }
  }, [connected, pending, navigate, requestAgentAppList, showToast])

  const workflow = async (activity: string, request: string, creation?: { name: unknown; authMode: unknown; uiTheme: unknown }) => {
    if (!connected) throw new Error('Reconnect to CraftBot before continuing.')
    const result = await frameworkRequest<{ sessionId: string }>({ operation: 'workflow', activity, request, ...(creation ? { creation } : {}) })
    onClose(); navigate(`/session/${result.sessionId}`)
  }
  const install = async (source: { id: string } | { from: string }) => {
    if (!connected) throw new Error('Reconnect to CraftBot before continuing.')
    const inspection = await frameworkRequest<{ status: string; data?: { installable: boolean; kind?: string; reason?: string }; stderr?: string }>({ operation: 'inspect', ...source })
    if (inspection.status !== 'success' || !inspection.data) throw new Error(inspection.stderr || 'Could not inspect this source.')
    if (!inspection.data.installable) {
      // An Agent App with an unavailable toolkit is not a foreign app to
      // rebuild automatically. Show the upstream refusal before starting work.
      if (inspection.data.kind === 'agent-app') throw new Error(inspection.data.reason || 'This app cannot be installed with the available toolkits.')
      await workflow('convert', `Import or convert this source using the importer workflow: ${'id' in source ? source.id : source.from}`)
      return
    }
    const job = await frameworkRequest<FrameworkInstallJob>({ operation: 'install', package: source })
    setPending(ids => [...ids, job.id])
    showToast('info', 'Installing app…', undefined, { key: `framework-install:${job.id}`, sticky: true })
    onClose()
  }
  const create = async (config: Record<string, unknown>, files: File[], icon: File | null) => {
    if (!connected) throw new Error('Reconnect to CraftBot before continuing.')
    const references: { name: string; path: string; kind: string }[] = []
    for (const file of [...files, ...(icon ? [icon] : [])]) {
      const body = new FormData(); body.append('file', file)
      const response = await fetch('/api/agent-app/stage', { method: 'POST', body })
      const result = await response.json() as { path?: string; error?: string }
      if (!response.ok || !result.path) throw new Error(result.error || `Could not upload ${file.name}`)
      references.push({ name: file.name, path: result.path, kind: file === icon ? 'icon' : 'reference' })
    }
    await workflow('create', `Create an app using these preferences. Clarify any missing requirements in this conversation. Use the framework's supported blueprint and styling options to match the requested design. Copy staged references into the app's reference directory.\n${JSON.stringify({ ...config, attachments: references }, null, 2)}`, { name: config.name, authMode: config.authMode, uiTheme: config.uiTheme })
  }
  return { install, create }
}
