/**
 * Generic data client for engine-generated CRUD (SYSTEM-MANAGED — do not edit)
 *
 * Every entity declared in config/schema.json already has a full REST API.
 * This module is the frontend half: typed CRUD calls and a React hook, so
 * components NEVER hand-write per-entity fetch plumbing.
 *
 *   import { useEntities } from '../services/data'
 *   import type { Card } from '../types.gen'
 *
 *   const cards = useEntities<Card>('cards', { columnId: col.id, orderBy: 'position' })
 *   // cards.items, cards.loading, cards.error
 *   // await cards.create({ title: 'New', columnId: col.id })
 *   // await cards.update(id, { title: 'Renamed' })
 *   // await cards.remove(id)
 *   // await cards.refresh()
 *
 * The plural is the entity's route path segment (BoardColumn ->
 * 'board_columns'); GET /api/_meta/schema lists them all. Custom endpoints
 * (routes.py) still go through ApiService.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

const BACKEND_URL =
  (window as any).__CRAFTBOT_BACKEND_URL__ || 'http://localhost:3101'

export interface ListParams {
  orderBy?: string
  order?: 'asc' | 'desc'
  limit?: number
  offset?: number
  /** Any schema field name -> equality filter value */
  [field: string]: string | number | boolean | undefined
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${BACKEND_URL}/api${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) {
    let detail = `${resp.status}`
    try {
      const data = await resp.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${method} /api${path} failed: ${detail}`)
  }
  return resp.json() as Promise<T>
}

function query(params?: ListParams): string {
  if (!params) return ''
  const q = Object.entries(params)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')
  return q ? `?${q}` : ''
}

// ── Change bus ──────────────────────────────────────────────────────────────
// Every mutation announces which plural changed; every mounted useEntities
// instance for that plural refreshes. This is what makes a create in one
// component appear instantly in every list that shows the entity — no
// lifted state, no context, no manual wiring. '*' refreshes everything
// (used by ApiService after custom-endpoint mutations, which may touch any
// entity).

type ChangeListener = (plural: string) => void
const changeListeners = new Set<ChangeListener>()

/** Announce that an entity list changed ('*' = unknown/any). Components
 * never need this — the data client and ApiService call it automatically;
 * call it manually only after mutating through some other channel. */
export function notifyEntitiesChanged(plural: string = '*'): void {
  for (const listener of changeListeners) {
    try {
      listener(plural)
    } catch {
      /* one bad listener must not break the rest */
    }
  }
}

/** One-off calls (outside React, or in AppController/custom logic). */
export const data = {
  list: <T>(plural: string, params?: ListParams) =>
    request<T[]>('GET', `/${plural}${query(params)}`),
  get: <T>(plural: string, id: number) => request<T>('GET', `/${plural}/${id}`),
  create: async <T>(plural: string, values: Partial<T>) => {
    const created = await request<T>('POST', `/${plural}`, values)
    notifyEntitiesChanged(plural)
    return created
  },
  bulkCreate: async <T>(plural: string, rows: Partial<T>[]) => {
    const created = await request<T[]>('POST', `/${plural}/bulk`, rows)
    notifyEntitiesChanged(plural)
    return created
  },
  update: async <T>(plural: string, id: number, values: Partial<T>) => {
    const updated = await request<T>('PUT', `/${plural}/${id}`, values)
    notifyEntitiesChanged(plural)
    return updated
  },
  remove: async (plural: string, id: number) => {
    const result = await request<{ status: string; deleted: number }>(
      'DELETE',
      `/${plural}/${id}`,
    )
    notifyEntitiesChanged(plural)
    return result
  },
}

// ── File storage (system routes — see backend/files_routes.py) ─────────────

export interface StoredFileMeta {
  id: number
  name: string
  mime: string | null
  size: number
  /** Relative API path; render as fileUrl(file) or store it in a field. */
  url: string
  createdAt: string | null
}

/** Absolute URL for a stored file (for <img src>, links, downloads). */
export function fileUrl(file: StoredFileMeta | string): string {
  const path = typeof file === 'string' ? file : file.url
  return path.startsWith('http') ? path : `${BACKEND_URL}${path}`
}

/** Upload one file; returns its metadata. Prefer the <FileUpload>/<ImageInput>
 * presets — use this directly only for custom flows. */
export async function uploadFile(file: File): Promise<StoredFileMeta> {
  const form = new FormData()
  form.append('file', file)
  const resp = await fetch(`${BACKEND_URL}/api/files`, { method: 'POST', body: form })
  if (!resp.ok) {
    let detail = `${resp.status}`
    try {
      const data = await resp.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`Upload failed: ${detail}`)
  }
  return resp.json() as Promise<StoredFileMeta>
}

export const files = {
  upload: uploadFile,
  list: () => request<StoredFileMeta[]>('GET', '/files'),
  remove: (id: number) =>
    request<{ status: string; deleted: number }>('DELETE', `/files/${id}`),
}

export interface EntityStore<T> {
  items: T[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  create: (values: Partial<T>) => Promise<T>
  update: (id: number, values: Partial<T>) => Promise<T>
  remove: (id: number) => Promise<void>
}

/**
 * Fetch + cache one entity list with CRUD helpers that auto-refresh.
 * Filters/ordering re-fetch when their values change.
 */
export function useEntities<T extends { id: number }>(
  plural: string,
  params?: ListParams,
): EntityStore<T> {
  const [items, setItems] = useState<T[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Stable dependency for object params without requiring callers to memoize.
  const paramsKey = JSON.stringify(params ?? {})

  const refresh = useCallback(async () => {
    try {
      setItems(await data.list<T>(plural, JSON.parse(paramsKey)))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [plural, paramsKey])

  useEffect(() => {
    setLoading(true)
    void refresh()
  }, [refresh])

  // Cross-component sync: refresh when ANY code mutates this entity —
  // another component's useEntities, raw data.* calls, or an ApiService
  // custom-endpoint mutation ('*').
  useEffect(() => {
    const listener: ChangeListener = (changed) => {
      if (changed === '*' || changed === plural) void refresh()
    }
    changeListeners.add(listener)
    return () => {
      changeListeners.delete(listener)
    }
  }, [plural, refresh])

  return useMemo(
    () => ({
      items,
      loading,
      error,
      refresh,
      create: async (values: Partial<T>) => {
        const created = await data.create<T>(plural, values)
        await refresh()
        return created
      },
      update: async (id: number, values: Partial<T>) => {
        const updated = await data.update<T>(plural, id, values)
        await refresh()
        return updated
      },
      remove: async (id: number) => {
        await data.remove(plural, id)
        await refresh()
      },
    }),
    [items, loading, error, refresh, plural],
  )
}
