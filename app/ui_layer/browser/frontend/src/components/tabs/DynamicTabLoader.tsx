import React, { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDynamicTabs } from '../../hooks/useDynamicTabs'
import { DynamicTabType } from '../../types/dynamicTabs'
import styles from './DynamicTab.module.css'

const VALID_TYPES: DynamicTabType[] = ['code', 'stock', 'planner', 'custom']

/**
 * Handles URL-based tab restoration.
 * When navigating to /dynamic/:type/:id and the tab doesn't exist in state,
 * this component auto-creates it and redirects.
 */
export function DynamicTabLoader() {
  const { type, id } = useParams<{ type: string; id: string }>()
  const { tabs, createTab } = useDynamicTabs()
  const navigate = useNavigate()

  useEffect(() => {
    if (!type || !id) {
      navigate('/', { replace: true })
      return
    }

    // Check if this tab already exists (race with route matching)
    const existingTab = tabs.find(t => t.path === `/dynamic/${type}/${id}`)
    if (existingTab) {
      // Tab exists but route didn't match — likely a timing issue, just stay
      return
    }

    // Validate tab type
    if (!VALID_TYPES.includes(type as DynamicTabType)) {
      navigate('/', { replace: true })
      return
    }

    // Create the tab and navigate to it
    const tab = createTab(type as DynamicTabType)
    navigate(tab.path, { replace: true })
  }, [type, id, tabs, createTab, navigate])

  return <DynamicTabFallback />
}

/**
 * Loading fallback shown while lazy tab components load.
 */
export function DynamicTabFallback() {
  return (
    <div className={styles.tabContainer}>
      <div className={styles.placeholder}>
        <p>Loading...</p>
      </div>
    </div>
  )
}
