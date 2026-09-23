import { useCallback, useEffect, useState } from 'react'
import i18n from '../../../i18n/config'
import { usePersistedState } from '../../../hooks/usePersistedState'
import { UI_STATE } from '../../../store/uiState'
import { STORAGE_VERSION } from './constants'
import { createDefaultLayout } from './defaultLayout'
import { boundsFor, normalizeLayouts, seedItem } from './normalizeLayouts'
import type { Breakpoint, BreakpointLayouts, DashboardLayoutsStorage, NamedLayout } from './types'
import { WIDGET_REGISTRY } from '../widgets/registry'

function isValidStorage(value: unknown): value is DashboardLayoutsStorage {
  return (
    !!value &&
    typeof value === 'object' &&
    Array.isArray((value as DashboardLayoutsStorage).layouts) &&
    (value as DashboardLayoutsStorage).layouts.length > 0
  )
}

function resolveLayouts(stored: DashboardLayoutsStorage | null): NamedLayout[] {
  // One schema, the current one. A version mismatch means the stored
  // numbers describe a grid that no longer exists — discard and reseed.
  // normalizeLayouts then re-applies sizing constraints, which live in
  // the constants and not in storage. Cloned because store values are
  // frozen and react-grid-layout expects plain objects.
  if (isValidStorage(stored) && stored.version === STORAGE_VERSION) {
    const normalized = normalizeLayouts(structuredClone(stored.layouts))
    if (normalized.length > 0) return normalized
  }
  return [createDefaultLayout()]
}

function makeLayoutId(): string {
  return `layout-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

// Per-breakpoint, because the bounds and the column count both are: a starting
// width of 4 would overflow the sm grid, and a minimum wider than the grid is
// unsatisfiable. Same seeding the grid itself uses, so a widget added to a
// layout is indistinguishable from one that shipped on it.
function emptyItemFor(widgetId: string, bp: Breakpoint) {
  return seedItem(widgetId, boundsFor(bp, widgetId))
}

export function useDashboardLayouts() {
  const [storedLayouts, setStoredLayouts] = usePersistedState(UI_STATE.dashboard.layouts)
  const [storedActiveId, setActiveLayoutId] = usePersistedState(UI_STATE.dashboard.activeLayoutId)

  // Working copy for the grid, resolved from persisted UI state once on
  // mount and mirrored back on every change. The store updates immediately
  // (so a drag right before navigating away is never lost); the persistence
  // middleware throttles the actual storage writes during drag/resize.
  const [layouts, setLayouts] = useState<NamedLayout[]>(() => resolveLayouts(storedLayouts))
  useEffect(() => {
    setStoredLayouts({ version: STORAGE_VERSION, layouts: structuredClone(layouts) })
  }, [layouts, setStoredLayouts])

  const activeLayoutId = layouts.some(l => l.id === storedActiveId) ? storedActiveId : layouts[0].id
  const activeLayout = layouts.find(l => l.id === activeLayoutId) ?? layouts[0]

  const updateActiveGridLayouts = useCallback((next: BreakpointLayouts) => {
    setLayouts(prev => prev.map(l => (
      l.id === activeLayoutId ? { ...l, layouts: next, updatedAt: Date.now() } : l
    )))
  }, [activeLayoutId])

  const addWidget = useCallback((widgetId: string) => {
    if (!WIDGET_REGISTRY[widgetId]) return
    setLayouts(prev => prev.map(l => {
      if (l.id !== activeLayoutId || l.widgetIds.includes(widgetId)) return l
      return {
        ...l,
        widgetIds: [...l.widgetIds, widgetId],
        layouts: {
          lg: [...l.layouts.lg, emptyItemFor(widgetId, 'lg')],
          md: [...l.layouts.md, emptyItemFor(widgetId, 'md')],
          sm: [...l.layouts.sm, emptyItemFor(widgetId, 'sm')],
        },
        updatedAt: Date.now(),
      }
    }))
  }, [activeLayoutId])

  const removeWidget = useCallback((widgetId: string) => {
    setLayouts(prev => prev.map(l => {
      if (l.id !== activeLayoutId) return l
      return {
        ...l,
        widgetIds: l.widgetIds.filter(id => id !== widgetId),
        layouts: {
          lg: l.layouts.lg.filter(item => item.i !== widgetId),
          md: l.layouts.md.filter(item => item.i !== widgetId),
          sm: l.layouts.sm.filter(item => item.i !== widgetId),
        },
        updatedAt: Date.now(),
      }
    }))
  }, [activeLayoutId])

  // Restores the seed arrangement on the active layout: default widgets return
  // to their original positions and sizes, and any removed ones come back.
  // Widgets the user added that aren't part of the default set are kept,
  // re-seeded at the bottom (y: Infinity) for the vertical compactor to pack.
  const resetLayout = useCallback(() => {
    const now = Date.now()
    const seed = createDefaultLayout(now)
    setLayouts(prev => prev.map(l => {
      if (l.id !== activeLayoutId) return l
      const extras = l.widgetIds.filter(id => !seed.widgetIds.includes(id))
      return {
        ...l,
        widgetIds: [...seed.widgetIds, ...extras],
        layouts: {
          lg: [...seed.layouts.lg, ...extras.map(id => emptyItemFor(id, 'lg'))],
          md: [...seed.layouts.md, ...extras.map(id => emptyItemFor(id, 'md'))],
          sm: [...seed.layouts.sm, ...extras.map(id => emptyItemFor(id, 'sm'))],
        },
        updatedAt: now,
      }
    }))
  }, [activeLayoutId])

  const createLayout = useCallback((name: string) => {
    const now = Date.now()
    const seed = createDefaultLayout(now)
    const newLayout: NamedLayout = {
      ...seed,
      id: makeLayoutId(),
      name: name.trim() || i18n.t('dashboard:layout.untitledName'),
      createdAt: now,
      updatedAt: now,
    }
    setLayouts(prev => [...prev, newLayout])
    setActiveLayoutId(newLayout.id)
  }, [setActiveLayoutId])

  const renameLayout = useCallback((id: string, name: string) => {
    const trimmed = name.trim()
    if (!trimmed) return
    setLayouts(prev => prev.map(l => (l.id === id ? { ...l, name: trimmed, updatedAt: Date.now() } : l)))
  }, [])

  const deleteLayout = useCallback((id: string) => {
    if (layouts.length <= 1) return
    const next = layouts.filter(l => l.id !== id)
    setLayouts(next)
    if (activeLayoutId === id) {
      setActiveLayoutId(next[0].id)
    }
  }, [layouts, activeLayoutId, setActiveLayoutId])

  return {
    layouts,
    activeLayout,
    activeLayoutId,
    setActiveLayoutId,
    updateActiveGridLayouts,
    addWidget,
    removeWidget,
    resetLayout,
    createLayout,
    renameLayout,
    deleteLayout,
  }
}
