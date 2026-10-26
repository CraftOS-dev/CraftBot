import type { RefObject } from 'react'
import { PanelLeft } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import styles from './PanelSwitcher.module.css'

/** A direct panel toggle. Content tabs live in the panel itself. */
export function PanelSwitcher({ label, panelOpen, onToggle, buttonRef, browsing = false, browserRunning = false }: {
  label: string
  panelOpen: boolean
  onToggle(): void
  buttonRef: RefObject<HTMLButtonElement>
  browsing?: boolean
  browserRunning?: boolean
}) {
  const { t } = useTranslation('chat')
  return <div className={styles.switcher}>
    <button type="button" ref={buttonRef} className={styles.trigger} aria-label={label}
      title={browsing ? t('browserPanel.browsing') : label} aria-expanded={panelOpen}
      data-panel-open={panelOpen} onClick={onToggle}>
      <PanelLeft size={16} />
      {browserRunning && <span className={`${styles.dot} ${browsing ? styles.busy : ''}`} aria-hidden="true" />}
    </button>
  </div>
}
