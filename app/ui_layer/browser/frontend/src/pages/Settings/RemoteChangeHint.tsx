import { useTranslation } from 'react-i18next'
import styles from './SettingsPage.module.css'

/**
 * Quiet notice for a `useServerDraft` whose server value changed under an
 * unsaved edit (another tab, the agent). "Load latest" drops the edit.
 */
export function RemoteChangeHint({ onLoadLatest }: { onLoadLatest: () => void }) {
  const { t } = useTranslation(['settings'])
  return (
    <span className={styles.statusWarning}>
      {t('settings:draft.changedElsewhere')}
      <button type="button" className={styles.draftLoadLatest} onClick={onLoadLatest}>
        {t('settings:draft.loadLatest')}
      </button>
    </span>
  )
}
