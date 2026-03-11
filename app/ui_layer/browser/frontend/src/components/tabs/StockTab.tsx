import React from 'react'
import { TrendingUp, TrendingDown, Minus, ArrowUpRight, ArrowDownRight } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useDynamicTabs } from '../../hooks/useDynamicTabs'
import { StockTabData } from '../../types/dynamicTabs'
import { MarkdownContent } from '../ui'
import styles from './DynamicTab.module.css'

interface StockTabProps {
  tabId: string
}

export const StockTab = React.memo(function StockTab({ tabId }: StockTabProps) {
  const { tabData, getTabById } = useDynamicTabs()
  const { actions } = useWebSocket()
  const tab = getTabById(tabId)
  const data = tabData[tabId] as StockTabData | undefined

  const taskActions = tab?.taskId
    ? actions.filter(a => a.parentId === tab.taskId || a.id === tab.taskId)
    : []

  const hasData = data && (data.ticker || data.chartData?.length || data.summary)

  if (!hasData) {
    return (
      <div className={styles.tabContainer}>
        {taskActions.length > 0 ? (
          <div className={styles.taskContent}>
            <div className={styles.taskHeader}>
              <TrendingUp size={20} />
              <h3>Stock Analysis</h3>
            </div>
            <div className={styles.actionList}>
              {taskActions.map(action => (
                <div key={action.id} className={`${styles.actionItem} ${styles[action.status]}`}>
                  <span className={styles.actionStatus}>{action.status}</span>
                  <span className={styles.actionName}>{action.name}</span>
                  {action.output && (
                    <div className={styles.actionOutput}>
                      <MarkdownContent content={action.output} />
                    </div>
                  )}
                </div>
              ))}
            </div>
            <p className={styles.waitingText}>Waiting for stock data...</p>
          </div>
        ) : (
          <div className={styles.placeholder}>
            <TrendingUp size={48} strokeWidth={1.5} />
            <h2>Stock Charts</h2>
            <p>Stock prices, market data, and financial charts will appear here when a stock-related task runs.</p>
          </div>
        )}
      </div>
    )
  }

  const isPositive = (data.change ?? 0) >= 0

  return (
    <div className={styles.tabContainer}>
      <div className={styles.taskContent}>
        {data.ticker && (
          <div className={styles.stockHeader}>
            <div className={styles.stockInfo}>
              <h2 className={styles.ticker}>{data.ticker}</h2>
              {data.name && <span className={styles.stockName}>{data.name}</span>}
            </div>
            {data.price !== undefined && (
              <div className={styles.priceInfo}>
                <span className={styles.price}>${data.price.toFixed(2)}</span>
                {data.change !== undefined && (
                  <span className={`${styles.change} ${isPositive ? styles.positive : styles.negative}`}>
                    {isPositive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                    {isPositive ? '+' : ''}{data.change.toFixed(2)}
                    {data.changePercent !== undefined && ` (${isPositive ? '+' : ''}${data.changePercent.toFixed(2)}%)`}
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        {data.chartData && data.chartData.length > 0 && (
          <div className={styles.dataSection}>
            <h4>Price History ({data.chartData.length} points)</h4>
            <div className={styles.miniChart}>
              {/* Simple text-based chart — real chart library can replace this */}
              <div className={styles.chartStats}>
                <span>High: ${Math.max(...data.chartData.map(d => d.high)).toFixed(2)}</span>
                <span>Low: ${Math.min(...data.chartData.map(d => d.low)).toFixed(2)}</span>
                <span>Vol: {data.chartData.reduce((s, d) => s + d.volume, 0).toLocaleString()}</span>
              </div>
            </div>
          </div>
        )}

        {data.summary && (
          <div className={styles.summarySection}>
            <MarkdownContent content={data.summary} />
          </div>
        )}
      </div>
    </div>
  )
})
