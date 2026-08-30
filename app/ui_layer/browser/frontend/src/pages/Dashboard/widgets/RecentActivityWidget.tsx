import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../../store/hooks'
import { selectAllActivity } from '../../../store/selectors/activity'
import { ActionBlock, ReasoningBlock } from '../../../components/activity/ActivityBlocks'
import i18n from '../../../i18n/config'
import { formatNumber } from '../../../i18n/format'
import styles from './widgets.module.css'

const MAX_ITEMS = 20

function formatRelativeTime(ms?: number): string {
  if (!ms) return ''
  const diff = Date.now() - ms
  if (diff < 60_000) return i18n.t('dashboard:widgets.recentActivity.justNow')
  if (diff < 3_600_000) return i18n.t('dashboard:widgets.recentActivity.minutesAgo', { count: Math.floor(diff / 60_000) })
  if (diff < 86_400_000) return i18n.t('dashboard:widgets.recentActivity.hoursAgo', { count: Math.floor(diff / 3_600_000) })
  return i18n.t('dashboard:widgets.recentActivity.daysAgo', { count: Math.floor(diff / 86_400_000) })
}

export function RecentActivityWidget() {
  const { t } = useTranslation(['dashboard'])
  const activity = useAppSelector(selectAllActivity)
  const recent = activity.slice(-MAX_ITEMS).reverse()

  // Tick once a second while anything visible is still running/waiting, so
  // the live elapsed timers (inside ActionBlock) and the relative "time
  // ago" labels below stay fresh. Coarser than Chat's 100ms ticker — not
  // needed at dashboard-widget granularity.
  const [, forceTick] = useState(0)
  const hasLive = recent.some(item => item.status === 'running' || item.status === 'waiting')
  useEffect(() => {
    if (!hasLive) return
    const id = setInterval(() => forceTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [hasLive])

  if (recent.length === 0) {
    return <div className={styles.emptyUsage}>{t('dashboard:widgets.recentActivity.empty')}</div>
  }

  return (
    <div className={styles.activityList}>
      {recent.map(item => {
        const tokens = (item.inputTokens ?? 0) + (item.outputTokens ?? 0)
        return (
          <div key={item.id} className={styles.activityRow}>
            {item.itemType === 'reasoning'
              ? <ReasoningBlock item={item} />
              : <ActionBlock item={item} />}
            <div className={styles.activityMeta}>
              <span>{formatRelativeTime(item.createdAt)}</span>
              {tokens > 0 && <span>{t('dashboard:widgets.recentActivity.tokens', { count: tokens, formattedCount: formatNumber(tokens) })}</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}
