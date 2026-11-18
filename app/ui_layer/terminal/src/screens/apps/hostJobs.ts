/**
 * Long-running Agent App jobs that outlive the Add screen: marketplace
 * installs and imports (a large repository downloads for minutes). Like the
 * browser's always-mounted creation hook, their state lives here at module
 * level: an install is a host job (`install`), followed by reading the
 * host's `snapshot` every few seconds, so leaving the screen never loses a
 * result: a toast reports it, and an open Add screen moves on to the app.
 *
 * A source that is not an Agent App package is converted instead: your AI
 * agent rebuilds it (the host's `workflow`, activity "convert").
 */
import { existsSync } from 'node:fs'
import { useSyncExternalStore } from 'react'
import i18next from 'i18next'
import { store } from '../../state/store'
import { pushToast } from '../../state/tuiSlice'
import { errorText, frameworkAppKey, frameworkRequest, requestAppList } from '../../apps/framework'
import type { FrameworkHostSnapshot, FrameworkInstallJob } from '../../../../browser/frontend/src/features/agentApps/frameworkApi'
import { isZipPath, importName, type CatalogueSource, type MarketplaceApp } from './hostModel'
import { checkLocalFile, expandPath, uploadImportZip } from './hostUpload'

const tr = (key: string, options?: Record<string, unknown>): string => i18next.t(`appsHost:${key}`, options ?? {})

// ── a tiny external store ───────────────────────────────────────────────────

interface Store<T> {
  get: () => T
  set: (next: T | ((prev: T) => T)) => void
  subscribe: (listener: () => void) => () => void
}

function createStore<T>(initial: T): Store<T> {
  let state = initial
  const listeners = new Set<() => void>()
  return {
    get: () => state,
    set(next) {
      state = typeof next === 'function' ? (next as (prev: T) => T)(state) : next
      listeners.forEach(l => l())
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}

function useStore<T>(s: Store<T>): T {
  return useSyncExternalStore(s.subscribe, s.get, s.get)
}

// ── installs (marketplace and import) ───────────────────────────────────────

export interface InstallJob {
  /** The host's job id. */
  id: string
  name: string
  /** The catalogue entry it installs, when it came from the marketplace. */
  sourceId?: string
  status: 'running' | 'success' | 'error' | 'interrupted'
  /** The last step the job reported, for one progress line. */
  step: string
  error: string | null
  /** The installed app's key (JSON [path, id]), once it is in. */
  appKey: string | null
}

/** Where a finished job or a conversion sends the Add screen; `seq` grows each time. */
export type Arrival = { kind: 'app'; appKey: string; seq: number } | { kind: 'build'; sessionId: string; seq: number }

interface JobsState {
  jobs: InstallJob[]
  arrival: Arrival | null
}

const jobs = createStore<JobsState>({ jobs: [], arrival: null })
let arrivalSeq = 0
let polling: ReturnType<typeof setTimeout> | null = null

export const useJobs = (): JobsState => useStore(jobs)

function arrive(arrival: { kind: 'app'; appKey: string } | { kind: 'build'; sessionId: string }): void {
  jobs.set(s => ({ ...s, arrival: { ...arrival, seq: ++arrivalSeq } as Arrival }))
}

function stepLine(job: FrameworkInstallJob): string {
  const last = job.steps[job.steps.length - 1]
  return last ? `${last.step}${last.status && last.status !== 'start' ? ` (${last.status})` : ''}` : ''
}

/** Read the host's jobs until none of ours is running. */
async function poll(): Promise<void> {
  polling = null
  const mine = jobs.get().jobs.filter(j => j.status === 'running')
  if (mine.length === 0) return
  try {
    const snapshot = await frameworkRequest<FrameworkHostSnapshot>({ operation: 'snapshot' })
    for (const job of snapshot.jobs.filter(j => mine.some(m => m.id === j.id))) {
      const problem = job.error || job.linkError || job.steps.find(step => step.error)?.error || null
      const done = job.status !== 'running'
      const installed = job.status === 'success' && !problem
      const appKey = job.result?.dir && job.result?.id ? frameworkAppKey(job.result.dir, job.result.id) : null
      const name = mine.find(m => m.id === job.id)?.name ?? ''
      jobs.set(s => ({
        ...s,
        jobs: s.jobs.map(j =>
          j.id === job.id
            ? { ...j, status: (job.status as InstallJob['status']) ?? 'running', step: stepLine(job), error: done && !installed ? problem || job.stderr || tr('market.installFailed') : null, appKey }
            : j,
        ),
      }))
      if (!done) continue
      requestAppList()
      if (installed) {
        store.dispatch(pushToast(tr('market.installedToast', { name: name || tr('market.app') }), 'success'))
        if (appKey) arrive({ kind: 'app', appKey })
      } else {
        store.dispatch(pushToast(tr('market.installAttention', { name: name || tr('market.app'), error: problem ?? '' }), 'error', 10_000))
      }
    }
  } catch (err) {
    store.dispatch(pushToast(tr('market.progressFailed', { error: errorText(err) }), 'error', 6000, 'framework-install-refresh'))
  }
  if (jobs.get().jobs.some(j => j.status === 'running')) polling = setTimeout(() => void poll(), 2500)
}

/**
 * Install from the catalogue (`{id}`) or from a source (`{from}`): a zip, a
 * folder, `github:owner/repo@ref/path`, a GitHub URL or `git+https://...#ref`.
 * Not an Agent App: your AI agent converts it, and the screen moves to that
 * build. Throws with the host's own words when it cannot start.
 */
export async function installSource(source: { id: string } | { from: string }, name: string): Promise<void> {
  const inspection = await frameworkRequest<{ status: string; data?: { installable: boolean; kind?: string; reason?: string }; stderr?: string }>({
    operation: 'inspect',
    ...source,
  })
  if (inspection.status !== 'success' || !inspection.data) throw new Error(inspection.stderr || tr('market.inspectFailed'))
  if (!inspection.data.installable) {
    // An Agent App whose toolkit is not available is refused, not rebuilt.
    if (inspection.data.kind === 'agent-app') throw new Error(inspection.data.reason || tr('market.notInstallable'))
    const what = 'id' in source ? source.id : source.from
    const result = await frameworkRequest<{ sessionId: string }>({
      operation: 'workflow',
      activity: 'convert',
      request: `Import or convert this source using the importer workflow: ${what}`,
    })
    arrive({ kind: 'build', sessionId: result.sessionId })
    return
  }
  const job = await frameworkRequest<FrameworkInstallJob>({ operation: 'install', package: source })
  jobs.set(s => ({
    ...s,
    jobs: [
      ...s.jobs.filter(j => j.id !== job.id),
      { id: job.id, name, sourceId: 'id' in source ? source.id : undefined, status: 'running', step: '', error: null, appKey: null },
    ],
  }))
  store.dispatch(pushToast(tr('market.installing', { name }), 'info'))
  if (!polling) polling = setTimeout(() => void poll(), 1000)
}

// ── marketplace ─────────────────────────────────────────────────────────────

export interface MarketState {
  apps: MarketplaceApp[]
  source: CatalogueSource | undefined
  loaded: boolean
  loading: boolean
  error: string | null
  /** Catalogue ids whose install is being started. */
  starting: string[]
}

const market = createStore<MarketState>({ apps: [], source: undefined, loaded: false, loading: false, error: null, starting: [] })

export const useMarketplace = (): MarketState => useStore(market)

/** Ask for the catalogue unless it is loaded (or loading); `force` reads it again. */
export function fetchMarketplace(force = false): void {
  const s = market.get()
  if (s.loading || (!force && s.loaded && !s.error)) return
  market.set({ ...s, loading: true, error: null })
  frameworkRequest<{ status: string; data?: { apps: MarketplaceApp[]; source?: CatalogueSource }; stderr?: string }>({ operation: 'catalogue' })
    .then(result => {
      if (result.status !== 'success' || !result.data) throw new Error(result.stderr || tr('market.loadFailed'))
      market.set(prev => ({ ...prev, apps: result.data!.apps, source: result.data!.source, loaded: true, loading: false }))
    })
    .catch(err => market.set(prev => ({ ...prev, loading: false, error: errorText(err) })))
}

export function installMarketplaceApp(app: MarketplaceApp): void {
  market.set(s => ({ ...s, starting: [...s.starting.filter(id => id !== app.id), app.id], error: null }))
  installSource({ id: app.id }, app.name)
    .catch(err => market.set(s => ({ ...s, error: errorText(err) })))
    .finally(() => market.set(s => ({ ...s, starting: s.starting.filter(id => id !== app.id) })))
}

// ── import ──────────────────────────────────────────────────────────────────

export interface ImportState {
  /** An import is being started from this client. */
  starting: boolean
  name: string
  error: string | null
}

const imports = createStore<ImportState>({ starting: false, name: '', error: null })

export const useImport = (): ImportState => useStore(imports)

/**
 * Import a source typed as text: a ZIP on this computer is uploaded first
 * (the host may be another machine); a folder on this computer goes by its
 * path; anything else (a URL, `github:...`) goes as typed.
 */
export async function startImport(input: string): Promise<void> {
  const raw = input.trim()
  if (!raw) return
  const name = importName(raw, tr('import.externalName'))
  imports.set({ starting: true, name, error: null })
  try {
    let from = raw
    if (isZipPath(raw)) {
      const file = checkLocalFile(raw)
      if (!file.ok) throw new Error(tr(file.reason === 'missing' ? 'files.missing' : 'files.notFile', { path: raw }))
      from = (await uploadImportZip(file.path, name)).path
    } else if (!/^[a-z][a-z+]*:/i.test(raw) || /^[a-z]:[\\/]/i.test(raw)) {
      // Not a URL: a path on this computer, made absolute for the host.
      const local = expandPath(raw)
      if (!existsSync(local)) throw new Error(tr('files.missing', { path: raw }))
      from = local
    }
    await installSource({ from }, name)
    imports.set(s => ({ ...s, starting: false }))
  } catch (err) {
    imports.set(s => ({ ...s, starting: false, error: errorText(err) }))
  }
}
