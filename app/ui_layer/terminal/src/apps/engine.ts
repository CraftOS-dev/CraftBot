/**
 * Talking to one Agent App from the terminal, over the A2App protocol.
 *
 * The client, the credential lookup and the remote identity checks are the
 * framework's own (the pinned package CraftBot runs the agent's CLI from), so
 * the terminal and the agent never disagree about credentials. The terminal
 * always works on the LIVE app, the one the browser shows, never a build's
 * dev instance. Operations come from the app's operations.json (or, for an
 * app reached by URL, from what it describes); screens are generated from
 * them (apps/view).
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { config } from '../config'
import type { FrameworkRegistryApp } from '../../../browser/frontend/src/types'
import { bindParams, generateViews, isReadOp, type Operation, type OpParam, type ViewsFile } from './view'

export { isReadOp }

/** The few client calls the terminal makes (the SDK's A2AppClient). */
interface Response {
  status: number
  body: string
  json: unknown
  ok: boolean
}
interface Client {
  baseUrl: string
  describe(path?: string): Promise<Record<string, unknown> | null>
  callOperation(name: string, args?: Record<string, unknown>, approvalKey?: string): Promise<Response>
  listRecords(entity: string, query?: { sort?: string; perPage?: number }): Promise<Response>
  pollEvents(since?: string): Promise<Response>
  request(method: string, path: string): Promise<Response>
}

interface Sdk {
  A2AppClient: new (opts: { baseUrl: string; token?: string | null; agentName?: string }) => Client
  credentialFor(origin: string, appId: string | null): string | null
  originOf(baseUrl: string): string
  readAgentToken(dir: string): string | null
  loadProject(dir: string): { dir: string; baseUrl: string; manifest: { id: string; name: string; modules?: { name: string; entities?: string[] }[] } }
  connect(app: string): Promise<{ client: Client }>
}

// Writes made from the terminal are attributed to the person at the
// terminal, not to an agent (the app records this on every write).
const AGENT_NAME = 'terminal'

/** The folder that holds app/vendor/agent-app/source.json, from this module upwards. */
function codeRoot(): string | null {
  let dir = dirname(fileURLToPath(import.meta.url))
  for (;;) {
    if (existsSync(join(dir, 'app', 'vendor', 'agent-app', 'source.json'))) return dir
    const up = dirname(dir)
    if (up === dir) return null
    dir = up
  }
}

/** The unpacked framework package, where CraftBot itself runs it from. */
export function packageDir(): string | null {
  const override = process.env.CRAFTBOT_AGENT_APP_PACKAGE?.trim()
  if (override) return resolve(override)
  const root = codeRoot()
  if (!root) return null
  try {
    const pin = JSON.parse(readFileSync(join(root, 'app', 'vendor', 'agent-app', 'source.json'), 'utf8')) as { sha256?: string }
    if (!pin.sha256) return null
    const dir = join(config().stateDir, 'runtime', 'agent-app', pin.sha256)
    return existsSync(join(dir, 'dist', 'lib', 'target.js')) ? dir : null
  } catch {
    return null
  }
}

let sdkLoad: Promise<Sdk> | null = null

async function sdk(): Promise<Sdk> {
  if (!sdkLoad) {
    sdkLoad = (async () => {
      const dir = packageDir()
      if (!dir) throw new OpError('The Agent App framework is not set up yet. Open Agent Apps once CraftBot has finished starting.', 0)
      const load = (rel: string) => import(pathToFileURL(join(dir, rel)).href) as Promise<Record<string, unknown>>
      const [client, remote, project, target] = await Promise.all([
        load('node_modules/@a2app/sdk/dist/index.js'),
        load('dist/lib/remote.js'),
        load('dist/lib/project.js'),
        load('dist/lib/target.js'),
      ])
      return { ...client, ...remote, ...project, ...target } as unknown as Sdk
    })()
    sdkLoad.catch(() => {
      sdkLoad = null
    })
  }
  return sdkLoad
}

export class OpError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message)
  }
}

/** The human part of an app's error envelope. */
function errorOf(res: Response): OpError {
  const body = (res.json ?? {}) as { message?: string; error?: string; code?: string }
  const message = body.message ?? body.error ?? (res.body.trim().slice(0, 300) || `HTTP ${res.status}`)
  return new OpError(message, res.status, body.code)
}

export interface Entity {
  name: string
  module: string
}

export interface LoadedApp {
  client: Client
  ops: Operation[]
  views: ViewsFile
  entities: Entity[]
  /** Reached by URL: its files are on another machine. */
  remote: boolean
}

/** Every operation a module describes, with the parameters its entities give. */
async function describedOps(client: Client): Promise<{ ops: Operation[]; modules: string[]; entities: Entity[] }> {
  const root = (await client.describe('')) as { modules?: { name: string }[] } | null
  if (!root) throw new OpError('The app did not describe itself.', 0)
  const ops = new Map<string, Operation>()
  const entities: Entity[] = []
  const modules = (root.modules ?? []).map(m => m.name)
  for (const module of modules) {
    const level = (await client.describe(module)) as {
      entities?: { name: string }[]
      operations?: { name: string; summary?: string; destructive?: boolean }[]
    } | null
    for (const op of level?.operations ?? []) {
      ops.set(op.name, { name: op.name, description: op.summary, destructive: op.destructive, module })
    }
    for (const entity of level?.entities ?? []) {
      entities.push({ name: entity.name, module })
      const detail = (await client.describe(`${module}/${entity.name}`)) as { operations?: Operation[] } | null
      for (const op of detail?.operations ?? []) ops.set(op.name, { ...op, module, entity: op.entity ?? entity.name })
    }
  }
  return { ops: [...ops.values()], modules, entities }
}

/** The entities each module describes (for apps whose manifest does not list them). */
async function describedEntities(client: Client, modules: string[]): Promise<Entity[]> {
  const out: Entity[] = []
  for (const module of modules) {
    const level = (await client.describe(module).catch(() => null)) as { entities?: { name: string }[] } | null
    for (const entity of level?.entities ?? []) out.push({ name: entity.name, module })
  }
  return out
}

/** Connect to an app and read what it offers. */
export async function loadApp(app: FrameworkRegistryApp): Promise<LoadedApp> {
  const s = await sdk()
  if (app.connection) {
    const { client } = await s.connect(app.connection.origin)
    const { ops, modules, entities } = await describedOps(client)
    return { client, ops, views: generateViews(ops, modules), entities, remote: true }
  }
  if (!existsSync(join(app.path, 'manifest.json'))) throw new OpError('This app\'s files are not on this computer.', 0)
  const project = s.loadProject(app.path)
  const token = s.credentialFor(s.originOf(project.baseUrl), project.manifest.id) ?? s.readAgentToken(project.dir)
  const client = new s.A2AppClient({ baseUrl: project.baseUrl, token, agentName: AGENT_NAME })
  const declared = join(project.dir, 'operations.json')
  let ops: Operation[]
  if (existsSync(declared)) {
    const file = JSON.parse(readFileSync(declared, 'utf8')) as { operations?: Operation[] }
    ops = file.operations ?? []
  } else {
    ops = (await describedOps(client)).ops
  }
  const modules = (project.manifest.modules ?? []).map(m => m.name)
  let entities = (project.manifest.modules ?? []).flatMap(m => (m.entities ?? []).map(name => ({ name, module: m.name })))
  if (entities.length === 0) entities = await describedEntities(client, modules)
  return { client, ops, views: generateViews(ops, modules), entities, remote: false }
}

export type OpOutcome = { kind: 'done'; data: unknown } | { kind: 'approval'; approvalKey: string }

/** An operation's result without the protocol's success envelope ({a2app, ok, operation, result}). */
export function unwrapResult(body: unknown): unknown {
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    const envelope = body as Record<string, unknown>
    if (envelope.a2app === true && envelope.ok === true && 'result' in envelope) return envelope.result
  }
  return body
}

/**
 * Run an operation. A destructive one first answers with an approval key;
 * the person confirms and it runs again with that key (the protocol's
 * approval flow: the terminal never approves on its own).
 */
export async function runOp(app: LoadedApp, op: Operation, params: Record<string, unknown>, approvalKey?: string): Promise<OpOutcome> {
  const res = await app.client.callOperation(op.name, params, approvalKey)
  const body = res.json as { code?: string; approvalKey?: string } | null
  if (res.status === 428 && body?.code === 'approval_required' && body.approvalKey && !approvalKey) {
    return { kind: 'approval', approvalKey: body.approvalKey }
  }
  if (!res.ok) throw errorOf(res)
  return { kind: 'done', data: unwrapResult(res.json ?? (res.body || null)) }
}

/** A read-only page of one entity's records, newest first when the app sorts. */
export async function listRecords(app: LoadedApp, entity: string): Promise<{ items: Record<string, unknown>[]; totalItems: number }> {
  let res = await app.client.listRecords(entity, { sort: '-created', perPage: 50 })
  if (!res.ok) res = await app.client.listRecords(entity, { perPage: 50 })
  if (!res.ok) throw errorOf(res)
  const parsed = (res.json ?? {}) as { items?: Record<string, unknown>[]; totalItems?: number }
  return { items: parsed.items ?? [], totalItems: parsed.totalItems ?? parsed.items?.length ?? 0 }
}

/** The app's work queue for your AI agent: requests waiting, running and done. */
export async function listTasks(app: LoadedApp): Promise<Record<string, unknown>[]> {
  const res = await app.client.request('GET', '/api/_a2app/tasks')
  if (!res.ok) throw errorOf(res)
  const parsed = res.json as { tasks?: Record<string, unknown>[] } | Record<string, unknown>[] | null
  return Array.isArray(parsed) ? parsed : (parsed?.tasks ?? [])
}

/** A param's value as the app expects it, from the text typed into its field. Throws on bad input. */
export function coerceParam(param: OpParam, text: string): unknown {
  const value = text.trim()
  switch (param.type) {
    case 'number': {
      const n = Number(value)
      if (!Number.isFinite(n)) throw new OpError('number', 0, 'number')
      return n
    }
    case 'boolean':
      return value === 'true'
    case 'list<enum>':
    case 'list<ref>':
      return value ? value.split(',').map(v => v.trim()).filter(Boolean) : []
    case 'json':
      try {
        return JSON.parse(value)
      } catch {
        throw new OpError('json', 0, 'json')
      }
    default:
      return value
  }
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
    if (Array.isArray(direct)) {
      out[name] = direct.join(', ')
      continue
    }
    if (direct !== undefined && direct !== null && typeof direct !== 'object') {
      out[name] = String(direct)
      continue
    }
    if ((name === 'id' || name.endsWith('_id') || name.endsWith('Id')) && row.id !== undefined) out[name] = String(row.id)
  }
  return out
}
