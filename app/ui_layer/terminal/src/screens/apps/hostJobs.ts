/**
 * Long-running Agent App jobs that outlive the Add screen: marketplace
 * installs (minutes), imports (a large repository downloads for minutes) and
 * the chat path's setup questions. Like the browser's always-mounted modal
 * and import toast, their state lives here at module level, fed by inbound
 * socket messages, so leaving the screen never loses a result: a toast
 * reports it, and an open Add screen moves on to the new app.
 */
import { useSyncExternalStore } from 'react'
import i18next from 'i18next'
import { onInboundMessage } from '../../../../browser/frontend/src/store/socket/socketMiddleware'
import { store } from '../../state/store'
import { send } from '../../state/hooks'
import { openScreen, pushToast } from '../../state/tuiSlice'
import {
  importAmount,
  importName,
  isZipPath,
  marketKey,
  pushProgressLine,
  type ImportProgressEvent,
  type InterviewQuestion,
  type MarketplaceApp,
} from './hostModel'
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

// ── marketplace ─────────────────────────────────────────────────────────────

export interface MarketState {
  apps: MarketplaceApp[]
  loaded: boolean
  loading: boolean
  error: string | null
  /** Install keys in flight. */
  installing: string[]
  /** Installs finished in this run, by install key ("Installed xN"). */
  counts: Record<string, number>
  /** The last batch of installs finished; `seq` grows each time. */
  installed: { projectId: string; seq: number } | null
}

const market = createStore<MarketState>({
  apps: [],
  loaded: false,
  loading: false,
  error: null,
  installing: [],
  counts: {},
  installed: null,
})

export const useMarketplace = (): MarketState => useStore(market)

const CATALOG_TIMEOUT_MS = 45_000
const INSTALL_TIMEOUT_MS = 3 * 60_000
let catalogTimer: ReturnType<typeof setTimeout> | null = null
const installTimers = new Map<string, ReturnType<typeof setTimeout>>()
const installNames = new Map<string, string>()
let pendingProjects: string[] = []
let installSeq = 0

/** Ask for the catalog unless it is loaded (or loading); `force` refetches. */
export function fetchMarketplace(force = false): void {
  const s = market.get()
  if (s.loading || (!force && s.loaded && !s.error)) return
  market.set({ ...s, loading: true, error: null })
  if (catalogTimer) clearTimeout(catalogTimer)
  // The backend always answers, but only if the request reached it.
  catalogTimer = setTimeout(() => {
    catalogTimer = null
    market.set(prev => ({ ...prev, loading: false, error: tr('market.loadFailed') }))
  }, CATALOG_TIMEOUT_MS)
  send('agent_app_marketplace_list')
}

export function installMarketplaceApp(app: MarketplaceApp, fields: Record<string, string>): void {
  const key = marketKey(app)
  installNames.set(key, fields.APP_TITLE || app.name)
  market.set(s => ({ ...s, installing: [...s.installing.filter(k => k !== key), key], error: null }))
  const old = installTimers.get(key)
  if (old) clearTimeout(old)
  installTimers.set(
    key,
    setTimeout(() => {
      installTimers.delete(key)
      market.set(s => ({
        ...s,
        installing: s.installing.filter(k => k !== key),
        error: tr('market.installTimeout', { name: installNames.get(key) ?? app.name }),
      }))
    }, INSTALL_TIMEOUT_MS),
  )
  send('agent_app_marketplace_install', {
    appId: key,
    appName: fields.APP_TITLE || app.name,
    appDescription: app.description,
    customFields: fields,
  })
}

function onMarketList(data: { success?: boolean; apps?: MarketplaceApp[]; error?: string }): void {
  if (catalogTimer) {
    clearTimeout(catalogTimer)
    catalogTimer = null
  }
  market.set(s =>
    data.success
      ? { ...s, apps: data.apps ?? [], loaded: true, loading: false, error: null }
      : { ...s, loading: false, error: data.error || tr('market.loadFailed') },
  )
}

function onMarketInstall(data: { status?: string; appId?: string; project?: { id?: string }; projectId?: string; error?: string }): void {
  const key = data.appId
  if (key) {
    const timer = installTimers.get(key)
    if (timer) clearTimeout(timer)
    installTimers.delete(key)
  }
  const name = (key && installNames.get(key)) || ''
  if (data.status === 'success') {
    const projectId = data.project?.id || data.projectId
    if (projectId) pendingProjects.push(projectId)
    market.set(s => {
      const installing = key ? s.installing.filter(k => k !== key) : []
      const counts = key ? { ...s.counts, [key]: (s.counts[key] ?? 0) + 1 } : s.counts
      if (installing.length > 0) return { ...s, installing, counts }
      // The batch is done: move on to the last app installed, as the browser does.
      const last = pendingProjects[pendingProjects.length - 1]
      pendingProjects = []
      return { ...s, installing, counts, installed: last ? { projectId: last, seq: ++installSeq } : s.installed }
    })
    store.dispatch(pushToast(tr('market.installedToast', { name: name || tr('market.app') }), 'success'))
  } else {
    market.set(s => ({
      ...s,
      installing: key ? s.installing.filter(k => k !== key) : [],
      error: data.error || tr('market.installFailed'),
    }))
    store.dispatch(pushToast(data.error || tr('market.installFailed'), 'error', 8000))
  }
}

// ── import ──────────────────────────────────────────────────────────────────

export interface ImportLine {
  phase: string
  text: string
}

export interface ImportState {
  /** An import started from this client is running. */
  running: boolean
  name: string
  lines: ImportLine[]
  /** The outcome of the last import; `seq` grows each time. */
  result: { success: boolean; projectId?: string; error?: string; seq: number } | null
}

const imports = createStore<ImportState>({ running: false, name: '', lines: [], result: null })
let importSeq = 0

export const useImport = (): ImportState => useStore(imports)

function finishImport(result: { success: boolean; projectId?: string; error?: string }): void {
  imports.set(s => ({ ...s, running: false, result: { ...result, seq: ++importSeq } }))
}

/**
 * Import from a GitHub URL, a local folder or a ZIP. A ZIP on this machine is
 * uploaded first (as the browser does), then the backend is told the source.
 */
export async function startImport(input: string): Promise<void> {
  const raw = input.trim()
  if (!raw) return
  const looksLocal = !/^[a-z][a-z0-9+.-]*:\/\//i.test(raw) && !/^git@/i.test(raw)
  const source = looksLocal ? expandPath(raw) : raw
  const name = importName(source, tr('import.externalName'))
  imports.set({ running: true, name, lines: [], result: imports.get().result })
  if (looksLocal && isZipPath(source)) {
    const file = checkLocalFile(source)
    if (!file.ok) {
      finishImport({ success: false, error: tr(file.reason === 'missing' ? 'files.missing' : 'files.notFile', { path: source }) })
      return
    }
    imports.set(s => ({ ...s, lines: pushProgressLine(s.lines, { phase: 'upload', text: tr('import.uploading', { name: file.name }) }) }))
    try {
      const staged = await uploadImportZip(file.path, name)
      send('agent_app_import', { source: staged.path, name: staged.name || name })
    } catch (err) {
      finishImport({ success: false, error: tr('import.uploadFailed', { message: err instanceof Error ? err.message : String(err) }) })
    }
    return
  }
  send('agent_app_import', { source, name })
}

function onImportProgress(data: ImportProgressEvent & { name?: string }): void {
  // Progress is broadcast to every client; show only imports started here.
  if (!imports.get().running) return
  const phase = data.phase || 'starting'
  const amount = importAmount(data, i18next.language)
  const label = phase.charAt(0).toUpperCase() + phase.slice(1)
  imports.set(s => ({ ...s, lines: pushProgressLine(s.lines, { phase, text: amount ? `${label}  ${amount}` : label }) }))
}

function onImportResult(data: { success?: boolean; projectId?: string; error?: string }): void {
  if (!imports.get().running) return
  const name = imports.get().name
  if (data.success) {
    finishImport({ success: true, projectId: data.projectId })
    store.dispatch(pushToast(tr('import.doneToast', { name }), 'success'))
  } else {
    finishImport({ success: false, error: data.error || tr('import.failed') })
    store.dispatch(pushToast(data.error || tr('import.failed'), 'error', 8000))
  }
}

// ── setup questions summoned from a chat ────────────────────────────────────

export interface WizardSeed {
  wizardId: string
  config: Record<string, unknown>
  questions: InterviewQuestion[]
  originSessionId?: string
}

let wizardSeed: WizardSeed | null = null

/** The setup questions a chat summoned, handed to the Add screen once. */
export function takeWizardSeed(): WizardSeed | null {
  const seed = wizardSeed
  wizardSeed = null
  return seed
}

/** The screen argument that opens the Add screen on a summoned wizard. */
export const WIZARD_SEED_ARG = 'wizard'

function onWizardOpen(data: Partial<WizardSeed>): void {
  if (!data?.wizardId || !Array.isArray(data.questions) || data.questions.length === 0) return
  wizardSeed = {
    wizardId: data.wizardId,
    config: data.config ?? {},
    questions: data.questions,
    ...(data.originSessionId ? { originSessionId: data.originSessionId } : {}),
  }
  // The browser pops its wizard up over whatever is open; so does this.
  store.dispatch(openScreen({ id: 'appCreate', arg: WIZARD_SEED_ARG }))
}

// ── inbound routing ─────────────────────────────────────────────────────────

onInboundMessage(msg => {
  const data = (msg.data ?? {}) as Record<string, unknown>
  switch (msg.type) {
    case 'agent_app_marketplace_list':
      onMarketList(data)
      break
    case 'agent_app_marketplace_install':
      onMarketInstall(data)
      break
    case 'agent_app_import_progress':
      onImportProgress(data)
      break
    case 'agent_app_import_result':
      onImportResult(data)
      break
    case 'agent_app_wizard_open':
      onWizardOpen(data as Partial<WizardSeed>)
      break
  }
})
