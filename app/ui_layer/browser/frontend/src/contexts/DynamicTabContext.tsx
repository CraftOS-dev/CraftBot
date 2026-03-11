import React, { createContext, useCallback, useEffect, useRef, useState } from 'react'
import {
  DynamicTab,
  DynamicTabPreferences,
  DynamicTabType,
  TabData,
  DEFAULT_TAB_PREFERENCES,
  PersistedTabState,
} from '../types/dynamicTabs'
import {
  generateTabId,
  generateTabPath,
  getDefaultTabIcon,
  getDefaultTabLabel,
} from '../services/tabDetectionService'

const STORAGE_KEY = 'craftbot-dynamic-tabs'

interface DynamicTabContextValue {
  tabs: DynamicTab[]
  tabData: Record<string, TabData>
  preferences: DynamicTabPreferences
  createTab: (type: DynamicTabType, label?: string, taskId?: string) => DynamicTab
  closeTab: (tabId: string) => void
  updateTabAccess: (tabId: string) => void
  renameTab: (tabId: string, newLabel: string) => void
  reorderTabs: (fromIndex: number, toIndex: number) => void
  setTabData: (tabId: string, data: TabData) => void
  mergeTabData: (tabId: string, data: Partial<TabData>) => void
  setPreferences: (prefs: Partial<DynamicTabPreferences>) => void
  getTabById: (tabId: string) => DynamicTab | undefined
  getTabByPath: (path: string) => DynamicTab | undefined
  getTabByTaskId: (taskId: string) => DynamicTab | undefined
}

export const DynamicTabContext = createContext<DynamicTabContextValue | null>(null)

function loadPersistedState(): PersistedTabState {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      return JSON.parse(stored)
    }
  } catch {
    // Ignore parse errors
  }
  return {
    tabs: [],
    activeTabId: null,
    userPreferences: DEFAULT_TAB_PREFERENCES,
  }
}

function savePersistedState(state: PersistedTabState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // Ignore storage errors
  }
}

export function DynamicTabProvider({ children }: { children: React.ReactNode }) {
  const initial = useRef(loadPersistedState())
  const [tabs, setTabs] = useState<DynamicTab[]>(initial.current.tabs)
  const [tabData, setTabDataState] = useState<Record<string, TabData>>({})
  const [preferences, setPreferencesState] = useState<DynamicTabPreferences>(
    initial.current.userPreferences
  )

  // Persist tab metadata on changes (not tab data — that's ephemeral/session-based)
  useEffect(() => {
    savePersistedState({
      tabs,
      activeTabId: null,
      userPreferences: preferences,
    })
  }, [tabs, preferences])

  // Cross-tab sync: listen for storage events from other browser tabs
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY || !e.newValue) return
      try {
        const state: PersistedTabState = JSON.parse(e.newValue)
        setTabs(state.tabs)
        setPreferencesState(state.userPreferences)
      } catch {
        // Ignore parse errors
      }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  const createTab = useCallback(
    (type: DynamicTabType, label?: string, taskId?: string): DynamicTab => {
      const id = generateTabId(type)
      const now = Date.now()
      const newTab: DynamicTab = {
        id,
        type,
        label: label ?? getDefaultTabLabel(type),
        iconName: getDefaultTabIcon(type),
        path: generateTabPath(type, id),
        taskId: taskId ?? null,
        createdAt: now,
        lastAccessed: now,
      }

      setTabs(prev => {
        let updated = [...prev, newTab]
        if (updated.length > preferences.maxTabs) {
          updated = updated
            .sort((a, b) => b.lastAccessed - a.lastAccessed)
            .slice(0, preferences.maxTabs)
        }
        return updated
      })

      return newTab
    },
    [preferences.maxTabs]
  )

  const closeTab = useCallback((tabId: string) => {
    setTabs(prev => prev.filter(tab => tab.id !== tabId))
    // Clean up tab data
    setTabDataState(prev => {
      const next = { ...prev }
      delete next[tabId]
      return next
    })
  }, [])

  const updateTabAccess = useCallback((tabId: string) => {
    setTabs(prev =>
      prev.map(tab =>
        tab.id === tabId ? { ...tab, lastAccessed: Date.now() } : tab
      )
    )
  }, [])

  const renameTab = useCallback((tabId: string, newLabel: string) => {
    setTabs(prev =>
      prev.map(tab =>
        tab.id === tabId ? { ...tab, label: newLabel } : tab
      )
    )
  }, [])

  const reorderTabs = useCallback((fromIndex: number, toIndex: number) => {
    setTabs(prev => {
      const updated = [...prev]
      const [moved] = updated.splice(fromIndex, 1)
      updated.splice(toIndex, 0, moved)
      return updated
    })
  }, [])

  const setTabData = useCallback((tabId: string, data: TabData) => {
    setTabDataState(prev => ({ ...prev, [tabId]: data }))
  }, [])

  const mergeTabData = useCallback((tabId: string, data: Partial<TabData>) => {
    setTabDataState(prev => ({
      ...prev,
      [tabId]: { ...(prev[tabId] ?? {}), ...data } as TabData,
    }))
  }, [])

  const setPreferences = useCallback((prefs: Partial<DynamicTabPreferences>) => {
    setPreferencesState(prev => ({ ...prev, ...prefs }))
  }, [])

  const getTabById = useCallback(
    (tabId: string) => tabs.find(tab => tab.id === tabId),
    [tabs]
  )

  const getTabByPath = useCallback(
    (path: string) => tabs.find(tab => path.startsWith(tab.path)),
    [tabs]
  )

  const getTabByTaskId = useCallback(
    (taskId: string) => tabs.find(tab => tab.taskId === taskId),
    [tabs]
  )

  return (
    <DynamicTabContext.Provider
      value={{
        tabs,
        tabData,
        preferences,
        createTab,
        closeTab,
        updateTabAccess,
        renameTab,
        reorderTabs,
        setTabData,
        mergeTabData,
        setPreferences,
        getTabById,
        getTabByPath,
        getTabByTaskId,
      }}
    >
      {children}
    </DynamicTabContext.Provider>
  )
}
