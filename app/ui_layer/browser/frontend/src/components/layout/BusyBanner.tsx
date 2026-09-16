import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { useAppSelector } from '../../store/hooks'
import { selectBackendBusy } from '../../store/selectors/connection'
import styles from './BusyBanner.module.css'

/**
 * Shown while connected but the backend isn't answering liveness pings — its
 * event loop is busy with long-running work. The UI stays usable and updates
 * resume on their own (docs/plans/ui-data-freshness-plan.md, §B5.3).
 */
export function BusyBanner() {
  const { t } = useTranslation('nav')
  const busy = useAppSelector(selectBackendBusy)
  if (!busy) return null
  return (
    <div className={styles.banner} role="status" aria-live="polite">
      <Loader2 size={14} className={styles.spinner} aria-hidden="true" />
      <span>{t('connection.backendBusy')}</span>
    </div>
  )
}
