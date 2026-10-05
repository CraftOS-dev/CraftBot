import { useTranslation } from 'react-i18next'
import { Sparkles } from 'lucide-react'
import { Button } from '../ui'
import type { PendingAgentAppSetup } from '../../types'
import styles from './ResumeSetupCard.module.css'

interface ResumeSetupCardProps {
  /** The oldest pending setup started from this chat. */
  setup: PendingAgentAppSetup
  /** Pending setups from this chat (this one included): "1 of N" when > 1. */
  queueTotal: number
  /** Reopen the setup's questions where the user left off. */
  onResume: () => void
  /** Ask to end the setup for good (the caller confirms). */
  onCancel: () => void
}

/**
 * Pinned above the chat composer while an Agent App setup this chat started
 * is unanswered, so closing its popup never loses it (issue #448). Sits in
 * the same slot as QuestionBox and shares its look.
 */
export function ResumeSetupCard({ setup, queueTotal, onResume, onCancel }: ResumeSetupCardProps) {
  const { t } = useTranslation(['chat'])

  return (
    <div className={styles.card} role="region" aria-label={t('chat:setupResume.aria')}>
      <Sparkles size={14} className={styles.icon} />
      <div className={styles.text}>
        <span className={styles.title}>{t('chat:setupResume.title', { name: setup.name })}</span>
        <span className={styles.hint}>{t('chat:setupResume.hint')}</span>
      </div>
      {queueTotal > 1 && (
        <span className={styles.queueBadge}>{t('chat:setupResume.queuePosition', { total: queueTotal })}</span>
      )}
      <div className={styles.actions}>
        <Button variant="ghost" size="sm" onClick={onCancel}>{t('chat:setupResume.cancel')}</Button>
        <Button variant="primary" size="sm" onClick={onResume}>{t('chat:setupResume.resume')}</Button>
      </div>
    </div>
  )
}
