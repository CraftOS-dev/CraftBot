import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../store/hooks'
import { RESOURCES, useResource } from '../../store/resources'
import { FrameworkSettingsCards } from '../../features/agentApps/FrameworkSettingsCards'
import styles from './SettingsPage.module.css'

export function AgentAppSettings() {
  const { t } = useTranslation('settings')
  useResource(RESOURCES.agentAppsList)
  const registry = useAppSelector(state => state.agentApp.framework)
  return <div className={styles.settingsSection}>
    <div className={styles.sectionHeader}>
      <h3>{t('agentApp.title')}</h3><p>{t('agentApp.subtitle')}</p>
    </div>
    <div className={styles.subsection}>
      <h4 className={styles.subsectionTitle}>{t('agentApp.projectsTitle')}</h4>
      <p className={styles.subsectionDesc}>{t('agentApp.projectsDesc')}</p>
      {registry.status === 'success' && !registry.apps.length && !registry.connected.length &&
        <div className={styles.emptyState}><p>{t('agentApp.noProjects')}</p></div>}
      <div className={styles.scheduleList}><FrameworkSettingsCards /></div>
    </div>
  </div>
}
