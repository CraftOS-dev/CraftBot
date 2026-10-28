/**
 * Talking to one Agent App from the terminal.
 *
 * Reuses the agent's own CLI library (agent-app/tools/src/lib/project.ts):
 * the same project resolution, the same agent token and superuser session,
 * the same shadow-instance routing. The terminal and the agent therefore can
 * never disagree about which instance or which credentials they use. Views
 * come from the shared view engine (agent-app/view): the app's declared
 * views.json, or views generated from its operations.
 */
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  authToken,
  loadOps,
  loadProject,
  request,
  type ProjectRef,
} from '../../../../../agent-app/tools/src/lib/project.ts'
import {
  bindParams,
  generateViews,
  isReadOp,
  validateViews,
  type Describe,
  type Operation,
  type ViewsFile,
} from '../../../../../agent-app/view/src/index.ts'

// Writes made from the terminal are attributed to the person at the
// terminal, not to an agent (the app records this on every write).
process.env.A2APP_AGENT = 'terminal'

export type { ProjectRef }

export interface LoadedApp {
  project: ProjectRef
  ops: Operation[]
  views: ViewsFile
  declared: boolean
  /** Problems in a declared views.json (the generated views are shown instead). */
  viewsProblems: string[]
}

export function loadApp(dir: string): LoadedApp {
  const project = loadProject(dir)
  const ops = loadOps(project) as Operation[]
  const path = join(project.dir, 'views.json')
  if (existsSync(path)) {
    try {
      const raw = JSON.parse(readFileSync(path, 'utf8')) as unknown
      const problems = validateViews(raw, ops)
      if (problems.length === 0) return { project, ops, views: raw as ViewsFile, declared: true, viewsProblems: [] }
      return { project, ops, views: generateViews(ops), declared: false, viewsProblems: problems.map(p => `${p.where}: ${p.message}`) }
    } catch (err) {
      return { project, ops, views: generateViews(ops), declared: false, viewsProblems: [String((err as Error).message)] }
    }
  }
  return { project, ops, views: generateViews(ops), declared: false, viewsProblems: [] }
}

export class OpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

/** The human part of an app's error envelope (never the hints written for agents). */
function errorMessage(body: string, status: number): string {
  try {
    const parsed = JSON.parse(body) as { message?: string; error?: string }
    const msg = parsed.message ?? parsed.error
    if (msg) return msg
  } catch {
    // Not JSON.
  }
  return body.trim().slice(0, 300) || `HTTP ${status}`
}

/** Run a declared operation with string params, as `agent-app run` does. */
export async function runOp(project: ProjectRef, op: Operation, params: Record<string, string>): Promise<unknown> {
  const exec = op.executor
  let method = (exec.method ?? 'POST').toUpperCase()
  let path = exec.path ?? ''
  let body: unknown
  if (exec.type === 'crud') {
    method = 'GET'
    path = `/api/collections/${exec.collection ?? ''}/records`
  }
  if (method === 'GET' || method === 'DELETE') {
    const qs = new URLSearchParams(params).toString()
    if (qs) path += (path.includes('?') ? '&' : '?') + qs
  } else {
    body = params
  }
  const res = await request(project, method, path, body)
  if (res.status < 200 || res.status >= 300) throw new OpError(errorMessage(res.body, res.status), res.status)
  if (!res.body) return null
  try {
    return JSON.parse(res.body) as unknown
  } catch {
    return res.body
  }
}

export async function describe(project: ProjectRef): Promise<Describe> {
  const res = await request(project, 'GET', '/api/_a2app/describe')
  if (res.status !== 200) throw new OpError(errorMessage(res.body, res.status), res.status)
  return JSON.parse(res.body) as Describe
}

/** Read-only page of one collection, newest first. */
export async function listRecords(project: ProjectRef, entity: string, page = 1): Promise<{ items: Record<string, unknown>[]; totalItems: number }> {
  const res = await request(project, 'GET', `/api/collections/${encodeURIComponent(entity)}/records?page=${page}&perPage=50&sort=-created`)
  if (res.status !== 200) throw new OpError(errorMessage(res.body, res.status), res.status)
  const parsed = JSON.parse(res.body) as { items?: Record<string, unknown>[]; totalItems?: number }
  return { items: parsed.items ?? [], totalItems: parsed.totalItems ?? 0 }
}

/**
 * Prefill an op's params from the selected row: explicit bindings first,
 * then any param named like a field of the row ("id", "<entity>_id").
 */
export function prefillFromRow(op: Operation, row: Record<string, unknown> | undefined, explicit?: Record<string, string | number | boolean>): Record<string, string> {
  const out = bindParams(explicit, row)
  if (!row) return out
  for (const name of Object.keys(op.params ?? {})) {
    if (out[name] !== undefined) continue
    const direct = row[name]
    if (direct !== undefined && direct !== null && typeof direct !== 'object') {
      out[name] = String(direct)
      continue
    }
    if ((name === 'id' || name.endsWith('_id') || name.endsWith('Id')) && row.id !== undefined) out[name] = String(row.id)
  }
  return out
}

export { isReadOp }

/**
 * Follow the app's live changes (PocketBase realtime over SSE) for some
 * collections. Calls `onChange` (debounced by the caller) on every create,
 * update or delete. Returns a function that stops following.
 */
export function followChanges(project: ProjectRef, collections: string[], onChange: (collection: string) => void): () => void {
  const controller = new AbortController()
  let stopped = false
  const run = async () => {
    try {
      const res = await fetch(`${project.baseUrl}/api/realtime`, {
        headers: { Accept: 'text/event-stream' },
        signal: controller.signal,
      })
      if (!res.ok || !res.body) return
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let event = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done || stopped) break
        buffer += decoder.decode(value, { stream: true })
        let nl: number
        while ((nl = buffer.indexOf('\n')) !== -1) {
          const line = buffer.slice(0, nl).replace(/\r$/, '')
          buffer = buffer.slice(nl + 1)
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) {
            const data = line.slice(5).trim()
            if (event === 'PB_CONNECT') {
              const { clientId } = JSON.parse(data) as { clientId: string }
              const token = await authToken(project).catch(() => null)
              await fetch(`${project.baseUrl}/api/realtime`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: token } : {}) },
                body: JSON.stringify({ clientId, subscriptions: collections.map(c => `${c}/*`) }),
                signal: controller.signal,
              })
            } else if (event) {
              onChange(event.split('/')[0] ?? event)
            }
          } else if (line === '') event = ''
        }
      }
    } catch {
      // Stopped, or the app went away: the screen's manual refresh still works.
    }
  }
  void run()
  return () => {
    stopped = true
    controller.abort()
  }
}
