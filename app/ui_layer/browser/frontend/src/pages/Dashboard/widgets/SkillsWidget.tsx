import { useState } from 'react'
import { Activity, CheckCircle } from 'lucide-react'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import styles from './widgets.module.css'

export function SkillsWidget() {
  const { dashboardMetrics } = useWebSocket()
  const [showAll, setShowAll] = useState(false)

  const skillEnabled = dashboardMetrics?.skill?.enabledSkills ?? 0
  const skillTotalInvocations = dashboardMetrics?.skill?.totalInvocations ?? 0
  const topSkills = dashboardMetrics?.skill?.topSkills ?? []

  return (
    <>
      <div className={styles.compactStats}>
        <div className={styles.compactStatItem}>
          <CheckCircle size={14} className={styles.successIcon} />
          <span className={styles.compactStatValue}>{skillEnabled}</span>
          <span className={styles.compactStatLabel}>Enabled</span>
        </div>
        <div className={styles.compactStatItem}>
          <Activity size={14} className={styles.primaryIcon} />
          <span className={styles.compactStatValue}>{skillTotalInvocations}</span>
          <span className={styles.compactStatLabel}>Invocations</span>
        </div>
      </div>
      <div className={styles.usageSection}>
        <div className={styles.usageSectionHeader}>Top Skills</div>
        {topSkills.length > 0 ? (
          <div className={styles.usageList}>
            {(showAll ? topSkills : topSkills.slice(0, 3)).map((skill, index) => (
              <div key={skill.name} className={styles.usageItem}>
                <span className={styles.usageRank}>#{index + 1}</span>
                <span className={styles.usageName}>{skill.name}</span>
                <span className={styles.usageCount}>{skill.count}</span>
              </div>
            ))}
            {topSkills.length > 3 && (
              <button className={styles.viewAllButton} onClick={() => setShowAll(!showAll)}>
                {showAll ? 'Show less' : `View all (${topSkills.length})`}
              </button>
            )}
          </div>
        ) : (
          <div className={styles.emptyUsage}>No usage yet</div>
        )}
      </div>
    </>
  )
}
