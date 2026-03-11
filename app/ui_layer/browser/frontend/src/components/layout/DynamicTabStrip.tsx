import React, { useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useDynamicTabs } from '../../hooks/useDynamicTabs'
import { useTabDragReorder } from '../../hooks/useTabDragReorder'
import { DynamicTab, DynamicTabType } from '../../types/dynamicTabs'
import { DynamicTabItem } from './DynamicTabItem'
import { AddTabMenu } from './AddTabMenu'
import styles from './NavBar.module.css'

/**
 * Renders the dynamic tab section of the navbar:
 * divider + draggable tab items + add-tab menu.
 */
export function DynamicTabStrip() {
  const navigate = useNavigate()
  const location = useLocation()
  const { tabs, createTab, closeTab, updateTabAccess, renameTab, reorderTabs } = useDynamicTabs()
  const drag = useTabDragReorder(reorderTabs)

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/'
    return location.pathname.startsWith(path)
  }

  const handleTabClick = useCallback((tab: DynamicTab) => {
    updateTabAccess(tab.id)
    navigate(tab.path)
  }, [updateTabAccess, navigate])

  const handleCloseTab = useCallback((e: React.MouseEvent, tabId: string) => {
    e.stopPropagation()
    const tab = tabs.find(t => t.id === tabId)
    closeTab(tabId)
    if (tab && isActive(tab.path)) {
      navigate('/')
    }
  }, [tabs, closeTab, navigate, location.pathname])

  const handleAddTab = useCallback((type: DynamicTabType) => {
    const tab = createTab(type)
    navigate(tab.path)
  }, [createTab, navigate])

  return (
    <>
      {tabs.length > 0 && <div className={styles.divider} />}

      {tabs.map((tab, index) => (
        <DynamicTabItem
          key={tab.id}
          tab={tab}
          isActive={isActive(tab.path)}
          index={index}
          dragIndex={drag.dragIndex}
          dragOverIndex={drag.dragOverIndex}
          onClose={handleCloseTab}
          onClick={handleTabClick}
          onRename={renameTab}
          onDragStart={drag.handleDragStart}
          onDragOver={drag.handleDragOver}
          onDragEnd={drag.handleDragEnd}
          onDrop={drag.handleDrop}
        />
      ))}

      <AddTabMenu onAddTab={handleAddTab} />
    </>
  )
}
