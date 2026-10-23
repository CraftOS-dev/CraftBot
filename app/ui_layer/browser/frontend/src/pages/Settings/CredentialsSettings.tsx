import { useTranslation } from 'react-i18next'
import { PasswordsPanel } from '../../components/MiniBrowser/PasswordsModal'
import styles from './SettingsPage.module.css'

export function CredentialsSettings() {
  const { t } = useTranslation('settings')

  return (
    <section className={styles.settingsSection}>
      <div className={`${styles.sectionHeader} ${styles.sectionHeaderFlush}`}>
        <h3>{t('nav.credentials')}</h3>
      </div>
      <PasswordsPanel />
    </section>
  )
}
