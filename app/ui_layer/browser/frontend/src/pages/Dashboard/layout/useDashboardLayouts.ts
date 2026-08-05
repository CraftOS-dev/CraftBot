import { useCallback, useEffect, useRef, useState } from 'react'
import { COLS, STORAGE_KEY_ACTIVE_ID, STORAGE_KEY_LAYOUTS } from './constants'
import { createDefaultLayout } from './defaultLayout'
import { normalizeLayouts } from './normalizeLayouts'
import type { BreakpointLayouts, DashboardLayoutsStorage, NamedLayout } from './types'
import { WIDGET_REGISTRY } from '../widgets/registry'

function isValidStorage(value: unknown): value is DashboardLayoutsStorage {
  return (
    !!value &&
    typeof value === 'object' &&
    Array.isArray((value as DashboardLayoutsStorage).layouts) &&
    (value as DashboardLayoutsStorage).layouts.length > 0
  )
}

function readLayouts(): NamedLayout[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_LAYOUTS)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (isValidStorage(parsed)) {
        // Sizing constraints live in the registry, not in storage — see
        // normalizeLayouts. Stored minW/minH are stale snapshots.
        const normalized = normalizeLayouts(parsed.layouts)
        if (normalized.length > 0) return normalized
      }
    }
  } catch {
    // Corrupt/unavailable storage — fall through to a fresh seed layout.
  }
  return [createDefaultLayout()]
}

function readActiveId(layouts: NamedLayout[]): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY_ACTIVE_ID)
    if (stored && layouts.some(l => l.id === stored)) return stored
  } catch {
    // ignore
  }
  return layouts[0].id
}

function writeLayouts(layouts: NamedLayout[]) {
  try {
    const payload: DashboardLayoutsStorage = { version: 1, layouts }
    localStorage.setItem(STORAGE_KEY_LAYOUTS, JSON.stringify(payload))
  } catch {
    // localStorage unavailable/full — layout just won't persist this session.
  }
}

function writeActiveId(id: string) {
  try {
    localStorage.setItem(STORAGE_KEY_ACTIVE_ID, id)
  } catch {
    // ignore
  }
}

function makeLayoutId(): string {
  return `layout-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

// `cols` is per-breakpoint: a default width of 6 would overflow the sm grid's
// 4 columns, and a minW wider than the grid is unsatisfiable.
function emptyItemFor(widgetId: string, cols: number) {
  const def = WIDGET_REGISTRY[widgetId].defaultLayout
  return {
    i: widgetId,
    x: 0,
    y: Infinity,
    w: Math.min(def.w, cols),
    h: def.h,
    minW: Math.min(def.minW ?? 1, cols),
    minH: def.minH ?? 1,
  }
}

export function useDashboardLayouts() {
  const [layouts, setLayouts] = useState<NamedLayout[]>(() => readLayouts())
  const [activeLayoutId, setActiveLayoutIdState] = useState<string>(() => readActiveId(layouts))

  // Debounce localStorage writes so continuous drag/resize ticks don't spam
  // storage (mirrors trading-view's 500ms layout-change debounce).
  const persistTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (persistTimer.current) clearTimeout(persistTimer.current)
    persistTimer.current = setTimeout(() => writeLayouts(layouts), 500)
    return () => {
      if (persistTimer.current) clearTimeout(persistTimer.current)
    }
  }, [layouts])

  useEffect(() => {
    writeActiveId(activeLayoutId)
  }, [activeLayoutId])

  const activeLayout = layouts.find(l => l.id === activeLayoutId) ?? layouts[0]

  const setActiveLayoutId = useCallback((id: string) => {
    setActiveLayoutIdState(id)
  }, [])

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
          lg: [...l.layouts.lg, emptyItemFor(widgetId, COLS.lg)],
          md: [...l.layouts.md, emptyItemFor(widgetId, COLS.md)],
          sm: [...l.layouts.sm, emptyItemFor(widgetId, COLS.sm)],
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

  const createLayout = useCallback((name: string) => {
    const now = Date.now()
    const seed = createDefaultLayout(now)
    const newLayout: NamedLayout = {
      ...seed,
      id: makeLayoutId(),
      name: name.trim() || 'Untitled',
      createdAt: now,
      updatedAt: now,
    }
    setLayouts(prev => [...prev, newLayout])
    setActiveLayoutIdState(newLayout.id)
  }, [])

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
      setActiveLayoutIdState(next[0].id)
    }
  }, [layouts, activeLayoutId])

  return {
    layouts,
    activeLayout,
    activeLayoutId,
    setActiveLayoutId,
    updateActiveGridLayouts,
    addWidget,
    removeWidget,
    createLayout,
    renameLayout,
    deleteLayout,
  }
}
