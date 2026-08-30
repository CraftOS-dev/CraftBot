import { Building2, Cpu, Hash } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import styles from './widgets.module.css'

export function ModelInfoWidget() {
  const { t } = useTranslation(['dashboard'])
  const { dashboardMetrics } = useWebSocket()

  const modelProvider = dashboardMetrics?.model?.provider ?? ''
  const modelId = dashboardMetrics?.model?.modelId ?? ''
  const modelName = dashboardMetrics?.model?.modelName ?? ''

  return (
    <div className={styles.modelInfo}>
      <div className={styles.modelItem}>
        <Building2 size={14} className={styles.mutedIcon} />
        <span className={styles.modelLabel}>{t('dashboard:widgets.modelInfo.provider')}</span>
        <span className={styles.modelValue}>{modelProvider || t('dashboard:widgets.modelInfo.notConfigured')}</span>
      </div>
      <div className={styles.modelItem}>
        <Cpu size={14} className={styles.mutedIcon} />
        <span className={styles.modelLabel}>{t('dashboard:widgets.modelInfo.model')}</span>
        <span className={styles.modelValue}>{modelName || t('dashboard:widgets.modelInfo.notConfigured')}</span>
      </div>
      <div className={styles.modelItem}>
        <Hash size={14} className={styles.mutedIcon} />
        <span className={styles.modelLabel}>{t('dashboard:widgets.modelInfo.modelId')}</span>
        <span className={styles.modelValueSmall}>{modelId || t('dashboard:widgets.modelInfo.notAvailable')}</span>
      </div>
    </div>
  )
}
