import React from 'react'
import { Monitor, RefreshCw, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { IconButton, Badge } from '../../components/ui'
import styles from './ScreenPage.module.css'

export function ScreenPage() {
  const { guiMode, footageUrl } = useWebSocket()

  return (
    <div className={styles.screenPage}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Monitor size={18} />
          <h2>Virtual Screen</h2>
          <Badge variant={guiMode ? 'success' : 'default'}>
            {guiMode ? 'Active' : 'Inactive'}
          </Badge>
        </div>
        <div className={styles.headerRight}>
          <IconButton icon={<ZoomOut size={16} />} tooltip="Zoom out" />
          <IconButton icon={<ZoomIn size={16} />} tooltip="Zoom in" />
          <IconButton icon={<Maximize2 size={16} />} tooltip="Fullscreen" />
          <IconButton icon={<RefreshCw size={16} />} tooltip="Refresh" />
        </div>
      </div>

      <div className={styles.screenContainer}>
        {footageUrl ? (
          <div className={styles.screenWrapper}>
            <img
              src={footageUrl}
              alt="Agent virtual screen"
              className={styles.screenshot}
            />
          </div>
        ) : (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>
              <Monitor size={48} />
            </div>
            <h3>No screen capture available</h3>
            <p>
              The agent's virtual screen will appear here when GUI mode is enabled.
            </p>
            {!guiMode && (
              <p className={styles.hint}>
                GUI mode is currently disabled. Enable it to see the agent's screen.
              </p>
            )}
          </div>
        )}
      </div>

      <div className={styles.footer}>
        <span className={styles.footerText}>
          Screen capture updates in real-time when the agent is working in GUI mode
        </span>
      </div>
    </div>
  )
}
