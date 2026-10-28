/**
 * Agent profile bundles over the backend's HTTP API, as the browser's
 * General tab uses them: export downloads a .craftbot file (saved where the
 * user says), import uploads one for a preview, then applies it by token.
 */
import { existsSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, join } from 'node:path'
import { getApiBaseUrl } from '../../platform/connection'
import { cleanPath, dispositionFilename, resolveExportPath } from './coreLogic'

export type ImportMode = 'replace' | 'overwrite'

export interface BundleManifest {
  name: string
  description?: string
  source_app_version?: string
  created_at?: string
  contents: {
    agent_name?: string
    md_files?: string[]
    skills?: string[]
    mcp_servers?: string[]
    agent_app_apps?: string[]
  }
}

export interface BundlePreview {
  skills_already_installed: string[]
  mcp_already_installed: string[]
  mcp_needs_env: Array<{ name: string; env_keys: string[] }>
}

export interface Inspected {
  manifest: BundleManifest
  preview: BundlePreview
  token: string
}

export interface ImportSummary {
  skills_added?: string[]
  mcp_added?: string[]
  agent_app_added?: string[]
  agent_app_renamed?: string[]
}

/** The folder an export is offered into: Downloads when it exists, else home. */
export function defaultExportFolder(): string {
  const downloads = join(homedir(), 'Downloads')
  return existsSync(downloads) ? downloads : homedir()
}

function isDirectory(path: string): boolean {
  try {
    return statSync(path).isDirectory()
  } catch {
    return false
  }
}

async function errorOf(resp: Response, fallback: string): Promise<string> {
  try {
    const body = (await resp.json()) as { error?: string }
    return body.error || fallback
  } catch {
    return fallback
  }
}

/** Download the current agent's bundle into `target` (a folder or a file path). Returns the path written. */
export async function exportProfile(target: string): Promise<string> {
  const resp = await fetch(`${getApiBaseUrl()}/api/profile/export`)
  if (!resp.ok) throw new Error(await errorOf(resp, `HTTP ${resp.status}`))
  const filename = dispositionFilename(resp.headers.get('Content-Disposition'))
  const input = cleanPath(target)
  const path = resolveExportPath(input, filename, isDirectory(input))
  const bytes = Buffer.from(await resp.arrayBuffer())
  writeFileSync(path, bytes)
  return path
}

/** Upload a bundle file for its manifest and preview. */
export async function inspectProfile(file: string): Promise<Inspected> {
  const path = cleanPath(file)
  if (!existsSync(path) || isDirectory(path)) throw new Error(`not a file: ${path}`)
  const form = new FormData()
  form.append('file', new Blob([readFileSync(path)], { type: 'application/octet-stream' }), basename(path))
  const resp = await fetch(`${getApiBaseUrl()}/api/profile/inspect`, { method: 'POST', body: form })
  const data = (await resp.json().catch(() => ({}))) as {
    success?: boolean
    error?: string
    manifest?: BundleManifest
    preview?: BundlePreview
    bundle_token?: string
  }
  if (!resp.ok || !data.success || !data.manifest || !data.bundle_token) {
    throw new Error(data.error || `HTTP ${resp.status}`)
  }
  return {
    manifest: data.manifest,
    preview: data.preview ?? { skills_already_installed: [], mcp_already_installed: [], mcp_needs_env: [] },
    token: data.bundle_token,
  }
}

/** Apply an inspected bundle. */
export async function importProfile(token: string, mode: ImportMode): Promise<ImportSummary> {
  const resp = await fetch(`${getApiBaseUrl()}/api/profile/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bundle_token: token, mode }),
  })
  const data = (await resp.json().catch(() => ({}))) as { success?: boolean; error?: string; summary?: ImportSummary }
  if (!resp.ok || !data.success) throw new Error(data.error || `HTTP ${resp.status}`)
  return data.summary ?? {}
}
