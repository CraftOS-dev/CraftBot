import { ArrowDownRight, ArrowUpRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import { formatBytes } from './shared'
import styles from './widgets.module.css'

export function SystemResourcesWidget() {
  const { t } = useTranslation(['dashboard'])
  const { dashboardMetrics } = useWebSocket()

  const cpuPercent = dashboardMetrics?.system.cpuPercent ?? 0
  const memoryPercent = dashboardMetrics?.system.memoryPercent ?? 0
  const memoryUsed = dashboardMetrics?.system.memoryUsedMb ?? 0
  const memoryTotal = dashboardMetrics?.system.memoryTotalMb ?? 0
  const diskPercent = dashboardMetrics?.system.diskPercent ?? 0
  const diskUsed = dashboardMetrics?.system.diskUsedGb ?? 0
  const diskTotal = dashboardMetrics?.system.diskTotalGb ?? 0
  const networkSentRate = dashboardMetrics?.system.networkSentRateKbps ?? 0
  const networkRecvRate = dashboardMetrics?.system.networkRecvRateKbps ?? 0

  const threadPoolActive = dashboardMetrics?.threadPool.activeThreads ?? 0
  const threadPoolMax = dashboardMetrics?.threadPool.maxWorkers ?? 16
  const threadPoolUtil = dashboardMetrics?.threadPool.utilizationPercent ?? 0

  return (
    <>
      <div className={styles.resourceGrid}>
        <div className={styles.resourceItem}>
          <div className={styles.resourceHeader}>
            <span>{t('dashboard:widgets.systemResources.cpu')}</span>
            <span className={cpuPercent > 80 ? styles.warning : ''}>{cpuPercent.toFixed(0)}%</span>
          </div>
          <div className={styles.resourceBar}>
            <div
              className={`${styles.resourceFill} ${cpuPercent > 80 ? styles.fillWarning : ''}`}
              style={{ width: `${Math.min(cpuPercent, 100)}%` }}
            />
          </div>
        </div>
        <div className={styles.resourceItem}>
          <div className={styles.resourceHeader}>
            <span>{t('dashboard:widgets.systemResources.memory')}</span>
            <span className={memoryPercent > 80 ? styles.warning : ''}>
              {formatBytes(memoryUsed)} / {formatBytes(memoryTotal)}
            </span>
          </div>
          <div className={styles.resourceBar}>
            <div
              className={`${styles.resourceFill} ${memoryPercent > 80 ? styles.fillWarning : ''}`}
              style={{ width: `${Math.min(memoryPercent, 100)}%` }}
            />
          </div>
        </div>
        <div className={styles.resourceItem}>
          <div className={styles.resourceHeader}>
            <span>{t('dashboard:widgets.systemResources.disk')}</span>
            <span className={diskPercent > 80 ? styles.warning : ''}>
              {diskUsed.toFixed(1)} GB / {diskTotal.toFixed(1)} GB
            </span>
          </div>
          <div className={styles.resourceBar}>
            <div
              className={`${styles.resourceFill} ${diskPercent > 80 ? styles.fillWarning : ''}`}
              style={{ width: `${Math.min(diskPercent, 100)}%` }}
            />
          </div>
        </div>
        <div className={styles.resourceItem}>
          <div className={styles.resourceHeader}>
            <span>{t('dashboard:widgets.systemResources.threadPool')}</span>
            <span className={threadPoolUtil > 80 ? styles.warning : ''}>
              {threadPoolActive} / {threadPoolMax} ({threadPoolUtil.toFixed(0)}%)
            </span>
          </div>
          <div className={styles.resourceBar}>
            <div
              className={`${styles.resourceFill} ${threadPoolUtil > 80 ? styles.fillWarning : ''}`}
              style={{ width: `${Math.min(threadPoolUtil, 100)}%` }}
            />
          </div>
        </div>
      </div>
      <div className={styles.networkRow}>
        <div className={styles.networkStat}>
          <ArrowUpRight size={14} className={styles.uploadIcon} />
          <span className={styles.networkLabel}>{t('dashboard:widgets.systemResources.upload')}</span>
          <span className={styles.networkValue}>{networkSentRate.toFixed(1)} KB/s</span>
        </div>
        <div className={styles.networkStat}>
          <ArrowDownRight size={14} className={styles.downloadIcon} />
          <span className={styles.networkLabel}>{t('dashboard:widgets.systemResources.download')}</span>
          <span className={styles.networkValue}>{networkRecvRate.toFixed(1)} KB/s</span>
        </div>
      </div>
    </>
  )
}
