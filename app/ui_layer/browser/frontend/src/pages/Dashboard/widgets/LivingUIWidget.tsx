import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Box, CheckCircle } from 'lucide-react'
import { useAppSelector } from '../../../store/hooks'
import { selectLivingUiProjects } from '../../../store/selectors/livingUi'
import { formatNumber } from '../../../i18n/format'
import styles from './widgets.module.css'

export function LivingUIWidget() {
  const { t } = useTranslation(['dashboard', 'common'])
  const projects = useAppSelector(selectLivingUiProjects)
  const [showAll, setShowAll] = useState(false)

  const runningCount = projects.filter(p => p.status === 'running').length

  return (
    <>
      <div className={styles.compactStats}>
        <div className={styles.compactStatItem}>
          <Box size={14} className={styles.primaryIcon} />
          <span className={styles.compactStatValue}>{formatNumber(projects.length)}</span>
          <span className={styles.compactStatLabel}>{t('dashboard:widgets.livingUi.installed')}</span>
        </div>
        <div className={styles.compactStatItem}>
          <CheckCircle size={14} className={styles.successIcon} />
          <span className={styles.compactStatValue}>{formatNumber(runningCount)}</span>
          <span className={styles.compactStatLabel}>{t('dashboard:widgets.livingUi.running')}</span>
        </div>
      </div>
      <div className={styles.usageSection}>
        <div className={styles.usageSectionHeader}>{t('dashboard:widgets.livingUi.projects')}</div>
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
          <div className={styles.emptyUsage}>{t('dashboard:widgets.livingUi.empty')}</div>
        )}
      </div>
    </>
  )
}
