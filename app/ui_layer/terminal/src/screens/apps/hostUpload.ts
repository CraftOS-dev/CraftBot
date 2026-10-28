/**
 * File transfer for the Agent App host screens, by path instead of a file
 * picker: reference files staged for the create wizard
 * (POST /api/agent-app/stage), ZIP imports (POST /api/agent-app/import) and
 * project exports (GET /api/agent-app/<id>/export). Plus copying text to the
 * terminal's clipboard with OSC 52 (sharing links, the project path).
 */
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'
import { getApiBaseUrl } from '../../platform/connection'

/** A typed path: surrounding quotes dropped, `~` expanded, made absolute. */
export function expandPath(input: string): string {
  let path = input.trim()
  if ((path.startsWith('"') && path.endsWith('"')) || (path.startsWith("'") && path.endsWith("'"))) path = path.slice(1, -1)
  if (path === '~') path = homedir()
  else if (path.startsWith('~/') || path.startsWith('~\\')) path = join(homedir(), path.slice(2))
  return path ? resolve(path) : ''
}

export type LocalFileCheck = { ok: true; path: string; name: string; size: number } | { ok: false; reason: 'missing' | 'notFile' }

export function checkLocalFile(input: string): LocalFileCheck {
  const path = expandPath(input)
  if (!path || !existsSync(path)) return { ok: false, reason: 'missing' }
  const stat = statSync(path)
  if (!stat.isFile()) return { ok: false, reason: 'notFile' }
  return { ok: true, path, name: basename(path), size: stat.size }
}

async function errorOf(resp: Response): Promise<string> {
  try {
    const body = (await resp.json()) as { error?: unknown; message?: unknown }
    const err = body.error ?? body.message
    if (typeof err === 'string' && err) return err
    if (err && typeof err === 'object' && 'message' in err) return String((err as { message: unknown }).message)
  } catch {
    // Not JSON.
  }
  return `HTTP ${resp.status}`
}

function formWithFile(path: string): FormData {
  const form = new FormData()
  form.append('file', new Blob([readFileSync(path)]), basename(path))
  return form
}

/** Stage one reference file for the wizard `wizardId` (moved into the project at finalize). */
export async function stageReference(wizardId: string, path: string): Promise<void> {
  const params = new URLSearchParams({ wizardId, kind: 'reference' })
  const resp = await fetch(`${getApiBaseUrl()}/api/agent-app/stage?${params}`, { method: 'POST', body: formWithFile(path) })
  if (!resp.ok) throw new Error(await errorOf(resp))
  const body = (await resp.json().catch(() => ({}))) as { error?: string }
  if (body.error) throw new Error(body.error)
}

/** Upload a ZIP for import; returns the server-side path to hand to `agent_app_import`. */
export async function uploadImportZip(path: string, name: string): Promise<{ path: string; name: string }> {
  const form = formWithFile(path)
  form.append('name', name)
  const resp = await fetch(`${getApiBaseUrl()}/api/agent-app/import`, { method: 'POST', body: form })
  if (!resp.ok) throw new Error(await errorOf(resp))
  const body = (await resp.json()) as { success?: boolean; path?: string; name?: string; error?: string }
  if (!body.success || !body.path) throw new Error(body.error || `HTTP ${resp.status}`)
  return { path: body.path, name: body.name || name }
}

/** Where an export goes by default: the Downloads folder when there is one, else home. */
export function defaultExportPath(fileName: string): string {
  const downloads = join(homedir(), 'Downloads')
  return join(existsSync(downloads) ? downloads : homedir(), fileName)
}

/** Download the project's ZIP export to `target`. Returns the bytes written. */
export async function exportProject(projectId: string, target: string): Promise<number> {
  const resp = await fetch(`${getApiBaseUrl()}/api/agent-app/${encodeURIComponent(projectId)}/export`)
  if (!resp.ok) throw new Error(await errorOf(resp))
  const bytes = Buffer.from(await resp.arrayBuffer())
  mkdirSync(dirname(target), { recursive: true })
  writeFileSync(target, bytes)
  return bytes.length
}

/** Copy text to the clipboard through the terminal (OSC 52). */
export function copyToClipboard(text: string): void {
  if (!process.stdout.isTTY) return
  process.stdout.write(`\u001B]52;c;${Buffer.from(text, 'utf8').toString('base64')}\u0007`)
}
