import React, { ButtonHTMLAttributes, forwardRef } from 'react'
import styles from './IconButton.module.css'

export type IconButtonSize = 'sm' | 'md' | 'lg'
export type IconButtonVariant = 'ghost' | 'secondary'

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: React.ReactNode
  size?: IconButtonSize
  variant?: IconButtonVariant
  active?: boolean
  tooltip?: string
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  (
    {
      icon,
      size = 'md',
      variant = 'ghost',
      active = false,
      tooltip,
      className = '',
      ...props
    },
    ref
  ) => {
    const classes = [
      styles.iconButton,
      styles[size],
      styles[variant],
      active ? styles.active : '',
      className,
    ]
      .filter(Boolean)
      .join(' ')

    return (
      <button
        ref={ref}
        className={classes}
        title={tooltip}
        {...props}
      >
        {icon}
      </button>
    )
  }
)

IconButton.displayName = 'IconButton'
