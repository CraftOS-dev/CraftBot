import { Building2, Cpu, Hash } from 'lucide-react'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import styles from './widgets.module.css'

export function ModelInfoWidget() {
  const { dashboardMetrics } = useWebSocket()

  const modelProvider = dashboardMetrics?.model?.provider ?? ''
  const modelId = dashboardMetrics?.model?.modelId ?? ''
  const modelName = dashboardMetrics?.model?.modelName ?? ''

  return (
    <div className={styles.modelInfo}>
      <div className={styles.modelItem}>
        <Building2 size={14} className={styles.mutedIcon} />
        <span className={styles.modelLabel}>Provider</span>
        <span className={styles.modelValue}>{modelProvider || 'Not configured'}</span>
      </div>
      <div className={styles.modelItem}>
        <Cpu size={14} className={styles.mutedIcon} />
        <span className={styles.modelLabel}>Model</span>
        <span className={styles.modelValue}>{modelName || 'Not configured'}</span>
      </div>
      <div className={styles.modelItem}>
        <Hash size={14} className={styles.mutedIcon} />
        <span className={styles.modelLabel}>Model ID</span>
        <span className={styles.modelValueSmall}>{modelId || 'N/A'}</span>
      </div>
    </div>
  )
}
