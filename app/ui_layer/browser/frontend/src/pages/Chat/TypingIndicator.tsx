import { useTranslation } from 'react-i18next'
import { StatusIndicator } from '../../components/ui'
import { WorkingLabel } from '../../components/activity/ActivityBlocks'
import styles from '../../components/activity/ActivityBlocks.module.css'

// In-timeline "Working…" row rendered as the LAST row of the session
// timeline while the agent is busy but no action row is currently
// running (running actions already show their own spinner). Reuses the
// action-row layout so the spinner and text align with action lines.
// ``status``: what the current step is doing, shown in place of "Working".
export function TypingIndicatorRow({ status }: { status?: string }) {
  const { t } = useTranslation(['chat', 'common'])
  return (
    <div className={styles.actionRow} role="status" aria-label={t('chat:working.aria')}>
      <span className={styles.actionRowStatus}>
        <StatusIndicator status="running" size="sm" />
      </span>
      <WorkingLabel status={status} fallback={t('chat:working.label')} />
    </div>
  )
}
