import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAppDispatch } from '../../store/hooks'
import { openTriggerReview } from '../../store/slices/agentAppSlice'
import type { AgentAppProject } from '../../types'
import styles from './AgentAppTriggerConsentBanner.module.css'

export function AgentAppTriggerConsentBanner({ project }: { project: AgentAppProject }) {
  const { t } = useTranslation('agentapp')
  const dispatch = useAppDispatch()
  const consent = project.triggerConsent
  // Only an undecided review, or requests that can't be read, need attention.
  // "Don't allow" is a decision; it can be changed in Settings.
  if (!consent || !(consent.needsReview || consent.error)) return null
  return <div className={styles.banner} role="status" aria-label={t('triggerConsent.permissions')}>
    <AlertTriangle size={14} className={styles.icon} aria-hidden />
    <span className={styles.message}>{consent.error || t(consent.triggers.some(request => request.change === 'approved')
      ? 'triggerConsent.pendingChanges' : 'triggerConsent.off')}</span>
    <button type="button" className={styles.review} onClick={() => dispatch(openTriggerReview(project.id))}>
      {t('triggerConsent.review')}
    </button>
  </div>
}
