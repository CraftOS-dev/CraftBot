import { useCallback, useEffect, useState } from 'react'

// Client-side UI preference: whether the mascot widget shows above the
// Tasks & Actions sidebar in chat. Persisted to localStorage and shared
// across mounted components via a same-tab custom event (the native
// `storage` event only fires for *other* tabs).
const STORAGE_KEY = 'craftbot-mascot-visible'
const EVENT_NAME = 'craftbot-mascot-visibility-change'

function readInitial(): boolean {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === null) return true
    return stored !== 'false'
  } catch {
    return true
  }
}

export function useMascotVisibility(): [boolean, (next: boolean) => void] {
  const [visible, setVisible] = useState<boolean>(readInitial)

  useEffect(() => {
    const handleCustom = (e: Event) => {
      const detail = (e as CustomEvent<boolean>).detail
      if (typeof detail === 'boolean') setVisible(detail)
    }
    const handleStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setVisible(e.newValue !== 'false')
    }
    window.addEventListener(EVENT_NAME, handleCustom)
    window.addEventListener('storage', handleStorage)
    return () => {
      window.removeEventListener(EVENT_NAME, handleCustom)
      window.removeEventListener('storage', handleStorage)
    }
  }, [])

  const set = useCallback((next: boolean) => {
    try {
      localStorage.setItem(STORAGE_KEY, next ? 'true' : 'false')
    } catch {
      // Ignore — falls back to in-memory state for this session.
    }
    window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: next }))
  }, [])

  return [visible, set]
}
