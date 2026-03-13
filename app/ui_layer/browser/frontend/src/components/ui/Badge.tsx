import React, { ReactNode } from 'react'
import styles from './Badge.module.css'

export type BadgeVariant = 'default' | 'primary' | 'success' | 'warning' | 'error' | 'info'

interface BadgeProps {
  children: ReactNode
  variant?: BadgeVariant
  dot?: boolean
  className?: string
}

export function Badge({
  children,
  variant = 'default',
  dot = false,
  className = '',
}: BadgeProps) {
  const classes = [
    styles.badge,
    styles[variant],
    dot ? styles.withDot : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <span className={classes}>
      {dot && <span className={styles.dot} />}
      {children}
    </span>
  )
}
