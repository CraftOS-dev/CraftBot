/**
 * File transfer for the Agent App host screens, by path instead of a file
 * picker: reference files and an icon staged for a new build
 * (POST /api/agent-app/stage) and ZIP imports (POST /api/agent-app/import).
 * Plus copying text to the terminal's clipboard with OSC 52.
 */
import { existsSync, readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, join, resolve } from 'node:path'
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

/** Stage one file for a new build; the builder copies it into the app's reference folder. */
export async function stageReference(path: string): Promise<{ name: string; path: string }> {
  const resp = await fetch(`${getApiBaseUrl()}/api/agent-app/stage`, { method: 'POST', body: formWithFile(path) })
  if (!resp.ok) throw new Error(await errorOf(resp))
  const body = (await resp.json().catch(() => ({}))) as { path?: string; error?: string }
  if (!body.path) throw new Error(body.error || `HTTP ${resp.status}`)
  return { name: basename(path), path: body.path }
}

/** Upload a ZIP for import; returns the server-side path to install from. */
export async function uploadImportZip(path: string, name: string): Promise<{ path: string; name: string }> {
  const form = formWithFile(path)
  form.append('name', name)
  const resp = await fetch(`${getApiBaseUrl()}/api/agent-app/import`, { method: 'POST', body: form })
  if (!resp.ok) throw new Error(await errorOf(resp))
  const body = (await resp.json()) as { success?: boolean; path?: string; name?: string; error?: string }
  if (!body.success || !body.path) throw new Error(body.error || `HTTP ${resp.status}`)
  return { path: body.path, name: body.name || name }
}

/** Copy text to the clipboard through the terminal (OSC 52). */
export function copyToClipboard(text: string): void {
  if (!process.stdout.isTTY) return
  process.stdout.write(`\u001B]52;c;${Buffer.from(text, 'utf8').toString('base64')}\u0007`)
}
