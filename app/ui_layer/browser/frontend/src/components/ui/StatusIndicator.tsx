import React from 'react'
import { CheckCircle, XCircle, Loader, Clock } from 'lucide-react'
import styles from './StatusIndicator.module.css'
import type { ActionStatus, AgentState } from '../../types'

interface StatusIndicatorProps {
  status: ActionStatus | AgentState
  size?: 'sm' | 'md' | 'lg'
  variant?: 'icon' | 'dot'
  pulse?: boolean
  className?: string
}

const iconSizeMap = {
  sm: 14,
  md: 16,
  lg: 20,
}

export function StatusIndicator({
  status,
  size = 'md',
  variant = 'icon',
  pulse = false,
  className = '',
}: StatusIndicatorProps) {
  const iconSize = iconSizeMap[size]

  // For 'dot' variant (agent status), render a colored dot
  if (variant === 'dot') {
    const shouldPulse = pulse || status === 'working' || status === 'thinking' || status === 'running'

    const dotClasses = [
      styles.dot,
      styles[`dot_${size}`],
      styles[`dot_${status}`] || styles.dot_pending,
      shouldPulse ? styles.pulse : '',
      className,
    ]
      .filter(Boolean)
      .join(' ')

    return <span className={dotClasses} />
  }

  // For 'icon' variant (task/action status), render lucide icons
  const getIcon = () => {
    switch (status) {
      case 'completed':
        return <CheckCircle size={iconSize} />
      case 'error':
      case 'cancelled':
        return <XCircle size={iconSize} />
      case 'running':
      case 'thinking':
      case 'working':
        return <Loader size={iconSize} className={styles.spinning} />
      case 'pending':
      case 'waiting':
      case 'idle':
      default:
        return <Clock size={iconSize} />
    }
  }

  const classes = [
    styles.indicator,
    styles[status] || styles.pending,
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return <span className={classes}>{getIcon()}</span>
}
