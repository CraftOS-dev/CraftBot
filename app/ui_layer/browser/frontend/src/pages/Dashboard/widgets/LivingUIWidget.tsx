import { useState } from 'react'
import { CheckCircle, Layers } from 'lucide-react'
import { useAppSelector } from '../../../store/hooks'
import { selectLivingUiProjects } from '../../../store/selectors/livingUi'
import styles from './widgets.module.css'

export function LivingUIWidget() {
  const projects = useAppSelector(selectLivingUiProjects)
  const [showAll, setShowAll] = useState(false)

  const runningCount = projects.filter(p => p.status === 'running').length

  return (
    <>
      <div className={styles.compactStats}>
        <div className={styles.compactStatItem}>
          <Layers size={14} className={styles.primaryIcon} />
          <span className={styles.compactStatValue}>{projects.length}</span>
          <span className={styles.compactStatLabel}>Installed</span>
        </div>
        <div className={styles.compactStatItem}>
          <CheckCircle size={14} className={styles.successIcon} />
          <span className={styles.compactStatValue}>{runningCount}</span>
          <span className={styles.compactStatLabel}>Running</span>
        </div>
      </div>
      <div className={styles.usageSection}>
        <div className={styles.usageSectionHeader}>Projects</div>
        {projects.length > 0 ? (
          <div className={styles.usageList}>
            {(showAll ? projects : projects.slice(0, 3)).map(p => (
              <div key={p.id} className={styles.usageItem}>
                <span className={styles.usageName}>{p.name}</span>
                <span className={styles.usageCount}>{p.status}</span>
              </div>
            ))}
            {projects.length > 3 && (
              <button className={styles.viewAllButton} onClick={() => setShowAll(!showAll)}>
                {showAll ? 'Show less' : `View all (${projects.length})`}
              </button>
            )}
          </div>
        ) : (
          <div className={styles.emptyUsage}>No Living UIs installed</div>
        )}
      </div>
    </>
  )
}
