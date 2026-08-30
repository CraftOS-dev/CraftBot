import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Box, CheckCircle } from 'lucide-react'
import { useAppSelector } from '../../../store/hooks'
import { selectAgentAppProjects } from '../../../store/selectors/agentApp'
import { formatNumber } from '../../../i18n/format'
import styles from './widgets.module.css'

export function AgentAppWidget() {
  const { t } = useTranslation(['dashboard', 'common'])
  const projects = useAppSelector(selectAgentAppProjects)
  const [showAll, setShowAll] = useState(false)

  const runningCount = projects.filter(p => p.status === 'running').length

  return (
    <>
      <div className={styles.compactStats}>
        <div className={styles.compactStatItem}>
          <Box size={14} className={styles.primaryIcon} />
          <span className={styles.compactStatValue}>{formatNumber(projects.length)}</span>
          <span className={styles.compactStatLabel}>{t('dashboard:widgets.agentApp.installed')}</span>
        </div>
        <div className={styles.compactStatItem}>
          <CheckCircle size={14} className={styles.successIcon} />
          <span className={styles.compactStatValue}>{formatNumber(runningCount)}</span>
          <span className={styles.compactStatLabel}>{t('dashboard:widgets.agentApp.running')}</span>
        </div>
      </div>
      <div className={styles.usageSection}>
        <div className={styles.usageSectionHeader}>{t('dashboard:widgets.agentApp.projects')}</div>
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
                {showAll ? t('common:actions.showLess') : t('dashboard:widgets.common.viewAllCount', { count: projects.length })}
              </button>
            )}
          </div>
        ) : (
          <div className={styles.emptyUsage}>{t('dashboard:widgets.agentApp.empty')}</div>
        )}
      </div>
    </>
  )
}
