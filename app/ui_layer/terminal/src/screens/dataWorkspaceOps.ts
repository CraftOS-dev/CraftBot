/**
 * Workspace requests, as the browser's WorkspaceContext makes them (that
 * module is a React provider of the browser app, so it cannot be used here).
 *
 * Each socket request carries a requestId the backend echoes. The shared
 * workspaceSlice applies only this client's own replies ('apply'), and a
 * 'reply-only' request (peeking into a folder) resolves without touching the
 * listing. Upload and download use the same HTTP endpoints as the browser:
 * upload copies a local file in, download streams a workspace file to disk.
 */
import { randomUUID } from 'node:crypto'
import { createWriteStream, openAsBlob } from 'node:fs'
import { mkdir, rename, rm } from 'node:fs/promises'
import { basename, dirname } from 'node:path'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import type { ReadableStream as WebReadableStream } from 'node:stream/web'
import { getSocketClient } from '../../../browser/frontend/src/store/socket/socketInstance'
import { onInboundMessage } from '../../../browser/frontend/src/store/socket/socketMiddleware'
import { releaseWorkspaceRequest, trackWorkspaceRequest } from '../../../browser/frontend/src/store/slices/workspaceSlice'
import type { FileUploadResponse } from '../../../browser/frontend/src/types'
import { getApiBaseUrl } from '../platform/connection'

const TIMEOUT_MS = 30_000

/** Why a request failed before the backend answered. */
export class RequestError extends Error {
  constructor(readonly code: 'notConnected' | 'timedOut') {
    super(code)
  }
}

interface Pending {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  timer: ReturnType<typeof setTimeout>
}

const pending = new Map<string, Pending>()
let listening = false

function listen(): void {
  if (listening) return
  listening = true
  // Delivered after the slices applied the message, like the browser's.
  onInboundMessage(msg => {
    if (!msg.type.startsWith('file_')) return
    const requestId = (msg.data as { requestId?: unknown } | undefined)?.requestId
    if (typeof requestId !== 'string') return
    const entry = pending.get(requestId)
    if (!entry) return
    clearTimeout(entry.timer)
    pending.delete(requestId)
    releaseWorkspaceRequest(requestId)
    entry.resolve(msg.data)
  })
}

/** Send one workspace request and wait for its reply. */
export function request<T>(type: string, data: Record<string, unknown>, mode: 'apply' | 'reply-only' = 'apply'): Promise<T> {
  listen()
  return new Promise<T>((resolve, reject) => {
    const client = getSocketClient()
    if (!client.isConnected) {
      reject(new RequestError('notConnected'))
      return
    }
    const requestId = randomUUID()
    const timer = setTimeout(() => {
      if (!pending.has(requestId)) return
      pending.delete(requestId)
      releaseWorkspaceRequest(requestId)
      reject(new RequestError('timedOut'))
    }, TIMEOUT_MS)
    pending.set(requestId, { resolve: resolve as (value: unknown) => void, reject, timer })
    trackWorkspaceRequest(requestId, mode)
    client.send(type, { ...data, requestId })
  })
}

/** Copy a local file into the workspace at `workspacePath` (POST /api/workspace/upload). */
export async function uploadLocalFile(localPath: string, workspacePath: string): Promise<FileUploadResponse> {
  const blob = await openAsBlob(localPath)
  const form = new FormData()
  form.append('file', blob, basename(localPath))
  const resp = await fetch(`${getApiBaseUrl()}/api/workspace/upload?path=${encodeURIComponent(workspacePath)}`, {
    method: 'POST',
    body: form,
  })
  const body = (await resp.json().catch(() => null)) as (FileUploadResponse & { error?: string }) | null
  if (!resp.ok || !body?.success) throw new Error(body?.error || `HTTP ${resp.status}`)
  return body
}

/**
 * Save a workspace file to a local path (GET /api/workspace/<path>?download=1),
 * streamed through a temporary ".part" file so a failed download never
 * leaves half a file under the real name.
 */
export async function downloadToLocal(workspacePath: string, target: string): Promise<void> {
  const url = `${getApiBaseUrl()}/api/workspace/${workspacePath.split('/').map(encodeURIComponent).join('/')}?download=1`
  const resp = await fetch(url)
  if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)
  await mkdir(dirname(target), { recursive: true })
  const part = `${target}.part`
  try {
    await pipeline(Readable.fromWeb(resp.body as unknown as WebReadableStream), createWriteStream(part))
    await rename(part, target)
  } catch (err) {
    await rm(part, { force: true }).catch(() => {})
    throw err
  }
}
