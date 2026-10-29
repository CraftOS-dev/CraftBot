import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui/Button'
import { useAppDispatch } from '../../store/hooks'
import { openTriggerReview } from '../../store/slices/agentAppSlice'
import type { AgentAppProject } from '../../types'
import styles from './AgentAppTriggerConsentBanner.module.css'

export function AgentAppTriggerConsentBanner({ project }: { project: AgentAppProject }) {
  const { t } = useTranslation('agentapp')
  const dispatch = useAppDispatch()
  const consent = project.triggerConsent
  if (!consent?.required) return null
  return <div className={styles.banner} role="status" aria-label={t('triggerConsent.permissions')}>
    <span>{consent.error || t(consent.triggers.some(request => request.change === 'approved')
      ? 'triggerConsent.pendingChanges' : 'triggerConsent.off')}</span>
    <Button variant="secondary" size="sm" onClick={() => dispatch(openTriggerReview(project.id))}>
      {t('triggerConsent.review')}
    </Button>
  </div>
}
