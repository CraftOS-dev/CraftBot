/**
 * Entity data hooks over the PocketBase SDK (SYSTEM-MANAGED — do not edit).
 *
 *   const cards = useEntities<Card>('cards', { filter: 'position > 0', sort: '-created' })
 *   // cards.items, cards.loading, cards.error
 *   // await cards.create({...}) / cards.update(id, {...}) / cards.remove(id)
 *
 * Realtime: every mounted useEntities subscribes to its collection, so a
 * mutation ANYWHERE (another component, custom pb_hooks route, the admin
 * UI) refreshes every list automatically — never lift entity state to
 * "sync" components. For one-off calls use the SDK directly:
 * `import { pb } from '../lib/pb'`.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { pb } from '../lib/pb'

export interface ListParams {
  /** PocketBase filter expression, e.g. `columnId = "${col.id}" && done = false` */
  filter?: string
  /** PocketBase sort, e.g. '-created' or 'position,-dueDate' */
  sort?: string
  /** Page size for server paging (with `page`). Omit = fetch all. */
  perPage?: number
  /** Alias for `perPage` (the common SQL/REST idiom). Either works. */
  limit?: number
  page?: number
  /** Expand relation fields, e.g. 'columnId' */
  expand?: string
}

export interface EntityStore<T> {
  items: T[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  create: (values: Partial<T>) => Promise<T>
  update: (id: string, values: Partial<T>) => Promise<T>
  remove: (id: string) => Promise<void>
  /** Aliases (react-query idiom). Canonical: items/loading/refresh. */
  data: T[]
  isLoading: boolean
  refetch: () => Promise<void>
}

// The generic DEFAULTS to a permissive record — an untyped call like
// `useEntities('cards')` yields fields typed `any` rather than degrading to
// `{ id: string }` (which made every field access a phantom type error and
// sent weak models thrashing). For FULL types, use the generated typed
// helpers from '../api.gen' (`useCards()` / `useEntities('cards')` typed via
// the collection map) or pass the type: `useEntities<Card>('cards')`.
export function useEntities<T extends { id: string } = Record<string, any> & { id: string }>(
  collection: string,
  params?: ListParams,
): EntityStore<T> {
  const [items, setItems] = useState<T[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const paramsKey = JSON.stringify(params ?? {})

  const refresh = useCallback(async () => {
    try {
      const p: ListParams = JSON.parse(paramsKey)
      const opts = {
        filter: p.filter,
        sort: p.sort,
        expand: p.expand,
      }
      // `limit` is accepted as an alias for `perPage` (common idiom).
      const pageSize = p.perPage ?? p.limit
      const rows = pageSize
        ? (await pb.collection(collection).getList<T>(p.page ?? 1, pageSize, opts)).items
        : await pb.collection(collection).getFullList<T>(opts)
      setItems(rows)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [collection, paramsKey])

  useEffect(() => {
    setLoading(true)
    void refresh()
  }, [refresh])

  // Cross-component sync via PocketBase realtime.
  useEffect(() => {
    let unsub: (() => void) | undefined
    pb.collection(collection)
      .subscribe('*', () => void refresh())
      .then(u => {
        unsub = u
      })
      .catch(() => {})
    return () => {
      unsub?.()
    }
  }, [collection, refresh])

  return useMemo(
    () => ({
      items,
      loading,
      error,
      refresh,
      create: async (values: Partial<T>) => {
        const created = await pb.collection(collection).create<T>(values)
        await refresh()
        return created
      },
      update: async (id: string, values: Partial<T>) => {
        const updated = await pb.collection(collection).update<T>(id, values)
        await refresh()
        return updated
      },
      remove: async (id: string) => {
        await pb.collection(collection).delete(id)
        await refresh()
      },
      data: items,
      isLoading: loading,
      refetch: refresh,
    }),
    [items, loading, error, refresh, collection],
  )
}

/** Low-level CRUD helpers over the PB SDK (prefer the api.gen helpers or
 * useEntities in components). */
export const data = {
  list: <T>(collection: string, params?: ListParams) =>
    pb.collection(collection).getFullList<T>({
      filter: params?.filter,
      sort: params?.sort,
      expand: params?.expand,
    }),
  get: <T>(collection: string, id: string) =>
    pb.collection(collection).getOne<T>(id),
  create: <T>(collection: string, values: Partial<T>) =>
    pb.collection(collection).create<T>(values),
  update: <T>(collection: string, id: string, values: Partial<T>) =>
    pb.collection(collection).update<T>(id, values),
  remove: (collection: string, id: string) =>
    pb.collection(collection).delete(id),
}

/** Legacy change-bus notifier. PocketBase realtime already pushes every
 * record mutation to all subscribed lists, so this is a no-op kept for
 * source compatibility (ApiService calls it after custom-endpoint
 * mutations — those mutate records via $app.save, which PB broadcasts). */
export function notifyEntitiesChanged(_collection: string): void {
  // intentionally empty — PB realtime is the change bus
}
