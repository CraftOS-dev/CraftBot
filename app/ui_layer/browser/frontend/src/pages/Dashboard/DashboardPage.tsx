import { useEffect } from 'react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { DashboardGrid } from './layout/DashboardGrid'
import { DashboardHeader } from './layout/DashboardHeader'
import { useDashboardLayouts } from './layout/useDashboardLayouts'
import styles from './DashboardPage.module.css'

export function DashboardPage() {
  const { connected, requestFilteredMetrics, subscribeDashboardMetrics, unsubscribeDashboardMetrics } = useWebSocket()

  const {
    layouts, activeLayout, activeLayoutId, setActiveLayoutId,
    updateActiveGridLayouts, addWidget, removeWidget, resetLayout,
    createLayout, renameLayout, deleteLayout,
  } = useDashboardLayouts()

  // Subscribe to live metrics while on this page, unsubscribe on leave.
  // Must depend on `connected`: the subscribe call is a no-op when the socket
  // isn't up yet, and the server keys its subscriber set by the socket object
  // and drops it on disconnect. Without this, a hard refresh straight to
  // /dashboard (socket still handshaking) or any reconnect would leave the
  // dashboard silently unsubscribed until the user navigated away and back.
  useEffect(() => {
    if (!connected) return
    subscribeDashboardMetrics()
    return () => {
      unsubscribeDashboardMetrics()
    }
  }, [connected, subscribeDashboardMetrics, unsubscribeDashboardMetrics])

  // Request 'total' metrics on initial load.
  useEffect(() => {
    if (connected) {
      requestFilteredMetrics('total')
    }
  }, [connected, requestFilteredMetrics])

  return (
    <div className={styles.dashboard}>
      <DashboardHeader
        layouts={layouts}
        activeLayout={activeLayout}
        activeLayoutId={activeLayoutId}
        onSelectLayout={setActiveLayoutId}
        onCreateLayout={createLayout}
        onRenameLayout={renameLayout}
        onDeleteLayout={deleteLayout}
        onResetLayout={resetLayout}
        onAddWidget={addWidget}
      />

      {/* The header stays put; only the grid scrolls. */}
      <div className={styles.gridArea}>
        <DashboardGrid
          activeLayout={activeLayout}
          onLayoutsChange={updateActiveGridLayouts}
          onRemoveWidget={removeWidget}
        />
      </div>
    </div>
  )
}
