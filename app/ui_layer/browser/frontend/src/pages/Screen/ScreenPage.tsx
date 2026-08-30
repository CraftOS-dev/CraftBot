import { Monitor, RefreshCw, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { IconButton, Badge } from '../../components/ui'
import styles from './ScreenPage.module.css'

export function ScreenPage() {
  const { t } = useTranslation(['workspace', 'common'])
  const { guiMode, footageUrl } = useWebSocket()

  return (
    <div className={styles.screenPage}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Monitor size={18} />
          <h2>{t('workspace:screen.title')}</h2>
          <Badge variant={guiMode ? 'success' : 'default'}>
            {guiMode ? t('workspace:screen.active') : t('workspace:screen.inactive')}
          </Badge>
        </div>
        <div className={styles.headerRight}>
          <IconButton icon={<ZoomOut size={16} />} tooltip={t('workspace:screen.zoomOut')} />
          <IconButton icon={<ZoomIn size={16} />} tooltip={t('workspace:screen.zoomIn')} />
          <IconButton icon={<Maximize2 size={16} />} tooltip={t('workspace:screen.fullscreen')} />
          <IconButton icon={<RefreshCw size={16} />} tooltip={t('common:actions.refresh')} />
        </div>
      </div>

      <div className={styles.screenContainer}>
        {footageUrl ? (
          <div className={styles.screenWrapper}>
            <img
              src={footageUrl}
              alt={t('workspace:screen.screenAlt')}
              className={styles.screenshot}
            />
          </div>
        ) : (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>
              <Monitor size={48} />
            </div>
            <h3>{t('workspace:screen.emptyTitle')}</h3>
            <p>
              {t('workspace:screen.emptyBody')}
            </p>
            {!guiMode && (
              <p className={styles.hint}>
                {t('workspace:screen.disabledHint')}
              </p>
            )}
          </div>
        )}
      </div>

      <div className={styles.footer}>
        <span className={styles.footerText}>
          {t('workspace:screen.footer')}
        </span>
      </div>
    </div>
  )
}
