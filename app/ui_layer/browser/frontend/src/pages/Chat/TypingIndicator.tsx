import { StatusIndicator } from '../../components/ui'
import styles from '../../components/activity/ActivityBlocks.module.css'

// In-timeline "Working…" row rendered as the LAST row of the session
// timeline while the agent is busy but no action row is currently
// running (running actions already show their own spinner). Reuses the
// action-row layout so the spinner and text align with action lines.
export function TypingIndicatorRow() {
  return (
    <div className={styles.actionRow} role="status" aria-label="Agent is working">
      <span className={styles.actionRowStatus}>
        <StatusIndicator status="running" size="sm" />
      </span>
      <span className={styles.workingLabel}>
        Working
        <span className={styles.workingDot}>.</span>
        <span className={styles.workingDot}>.</span>
        <span className={styles.workingDot}>.</span>
      </span>
    </div>
  )
}
