/**
 * Living UI Component Library
 *
 * Pre-built components matching CraftBot browser interface design.
 * Use these by default - avoid creating custom styles.
 *
 * Usage:
 *   import { Button, Card, Input, Alert } from './components/ui'
 */

import React, {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  TextareaHTMLAttributes,
  SelectHTMLAttributes,
  ReactNode,
  forwardRef,
  useState,
  useEffect,
  useId,
  createContext,
  useContext,
} from 'react'
import { createPortal } from 'react-dom'

// =============================================================================
// BUTTON
// =============================================================================

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  fullWidth?: boolean
  icon?: ReactNode
  iconPosition?: 'left' | 'right'
}

const buttonStyles: Record<string, React.CSSProperties> = {
  base: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 'var(--space-2)',
    fontFamily: 'var(--font-sans)',
    fontWeight: 'var(--font-weight-medium)' as any,
    border: 'none',
    borderRadius: 'var(--radius-md)',
    cursor: 'pointer',
    transition: 'var(--transition-base)',
    whiteSpace: 'nowrap',
  },
  primary: {
    backgroundColor: 'var(--color-primary)',
    color: 'var(--color-white)',
  },
  secondary: {
    backgroundColor: 'var(--bg-tertiary)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-primary)',
  },
  danger: {
    backgroundColor: 'var(--color-error)',
    color: 'var(--color-white)',
  },
  ghost: {
    backgroundColor: 'transparent',
    color: 'var(--text-secondary)',
  },
  sm: {
    height: 'var(--input-height-sm)',
    padding: '0 var(--space-2)',
    fontSize: 'var(--font-size-xs)',
  },
  md: {
    height: 'var(--input-height-md)',
    padding: '0 var(--space-3)',
    fontSize: 'var(--font-size-sm)',
  },
  lg: {
    height: 'var(--input-height-lg)',
    padding: '0 var(--space-4)',
    fontSize: 'var(--font-size-base)',
  },
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      children,
      variant = 'primary',
      size = 'md',
      loading = false,
      fullWidth = false,
      icon,
      iconPosition = 'left',
      disabled,
      style,
      onMouseEnter,
      onMouseLeave,
      ...props
    },
    ref
  ) => {
    const [isHovered, setIsHovered] = useState(false)

    const hoverStyles: Record<ButtonVariant, React.CSSProperties> = {
      primary: { backgroundColor: 'var(--color-primary-hover)' },
      secondary: { backgroundColor: 'var(--color-gray-700)' },
      danger: { backgroundColor: '#DC2626' },
      ghost: { backgroundColor: 'var(--bg-tertiary)' },
    }

    const combinedStyle: React.CSSProperties = {
      ...buttonStyles.base,
      ...buttonStyles[variant],
      ...buttonStyles[size],
      ...(fullWidth && { width: '100%' }),
      ...(disabled && { opacity: 0.5, cursor: 'not-allowed' }),
      ...(loading && { pointerEvents: 'none' as const }),
      ...(isHovered && !disabled && hoverStyles[variant]),
      ...style,
    }

    return (
      <button
        ref={ref}
        style={combinedStyle}
        disabled={disabled || loading}
        onMouseEnter={(e) => {
          setIsHovered(true)
          onMouseEnter?.(e)
        }}
        onMouseLeave={(e) => {
          setIsHovered(false)
          onMouseLeave?.(e)
        }}
        {...props}
      >
        {loading && <Spinner size={size === 'sm' ? 12 : size === 'lg' ? 18 : 14} />}
        {!loading && icon && iconPosition === 'left' && icon}
        {children}
        {!loading && icon && iconPosition === 'right' && icon}
      </button>
    )
  }
)

Button.displayName = 'Button'

// =============================================================================
// SPINNER (Internal)
// =============================================================================

interface SpinnerProps {
  size?: number
}

function Spinner({ size = 16 }: SpinnerProps) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        border: '2px solid var(--border-primary)',
        borderTopColor: 'var(--color-primary)',
        borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
      }}
    />
  )
}

// =============================================================================
// INPUT
// =============================================================================

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  hint?: string
}

const inputBaseStyle: React.CSSProperties = {
  width: '100%',
  height: 'var(--input-height-md)',
  padding: '0 var(--space-3)',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--font-size-base)',
  backgroundColor: 'var(--bg-secondary)',
  color: 'var(--text-primary)',
  border: '1px solid var(--border-primary)',
  borderRadius: 'var(--radius-md)',
  transition: 'var(--transition-base)',
  outline: 'none',
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, id, style, ...props }, ref) => {
    const generatedId = useId()
    const inputId = id || generatedId

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        {label && (
          <label
            htmlFor={inputId}
            style={{
              fontSize: 'var(--font-size-sm)',
              fontWeight: 'var(--font-weight-medium)' as any,
              color: 'var(--text-primary)',
            }}
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          style={{
            ...inputBaseStyle,
            ...(error && { borderColor: 'var(--color-error)' }),
            ...style,
          }}
          {...props}
        />
        {hint && !error && (
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)' }}>
            {hint}
          </span>
        )}
        {error && (
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-error)' }}>
            {error}
          </span>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'

// =============================================================================
// TEXTAREA
// =============================================================================

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  error?: string
  hint?: string
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, hint, id, style, rows = 4, ...props }, ref) => {
    const generatedId = useId()
    const inputId = id || generatedId

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        {label && (
          <label
            htmlFor={inputId}
            style={{
              fontSize: 'var(--font-size-sm)',
              fontWeight: 'var(--font-weight-medium)' as any,
              color: 'var(--text-primary)',
            }}
          >
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={inputId}
          rows={rows}
          style={{
            ...inputBaseStyle,
            height: 'auto',
            padding: 'var(--space-2) var(--space-3)',
            resize: 'vertical',
            ...(error && { borderColor: 'var(--color-error)' }),
            ...style,
          }}
          {...props}
        />
        {hint && !error && (
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)' }}>
            {hint}
          </span>
        )}
        {error && (
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-error)' }}>
            {error}
          </span>
        )}
      </div>
    )
  }
)

Textarea.displayName = 'Textarea'

// =============================================================================
// SELECT
// =============================================================================

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  label?: string
  error?: string
  hint?: string
  options: SelectOption[]
  placeholder?: string
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, hint, options, placeholder, id, style, ...props }, ref) => {
    const generatedId = useId()
    const inputId = id || generatedId

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        {label && (
          <label
            htmlFor={inputId}
            style={{
              fontSize: 'var(--font-size-sm)',
              fontWeight: 'var(--font-weight-medium)' as any,
              color: 'var(--text-primary)',
            }}
          >
            {label}
          </label>
        )}
        <select
          ref={ref}
          id={inputId}
          style={{
            ...inputBaseStyle,
            cursor: 'pointer',
            ...(error && { borderColor: 'var(--color-error)' }),
            ...style,
          }}
          {...props}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
        {hint && !error && (
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)' }}>
            {hint}
          </span>
        )}
        {error && (
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-error)' }}>
            {error}
          </span>
        )}
      </div>
    )
  }
)

Select.displayName = 'Select'

// =============================================================================
// CHECKBOX
// =============================================================================

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: string
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ label, id, style, ...props }, ref) => {
    const generatedId = useId()
    const inputId = id || generatedId

    return (
      <label
        htmlFor={inputId}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
          cursor: 'pointer',
          fontSize: 'var(--font-size-base)',
          color: 'var(--text-primary)',
        }}
      >
        <input
          ref={ref}
          type="checkbox"
          id={inputId}
          style={{
            width: 16,
            height: 16,
            accentColor: 'var(--color-primary)',
            cursor: 'pointer',
            ...style,
          }}
          {...props}
        />
        {label}
      </label>
    )
  }
)

Checkbox.displayName = 'Checkbox'

// =============================================================================
// TOGGLE
// =============================================================================

export interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label?: string
  disabled?: boolean
}

export function Toggle({ checked, onChange, label, disabled }: ToggleProps) {
  const id = useId()

  return (
    <label
      htmlFor={id}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <button
        id={id}
        role="switch"
        type="button"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        style={{
          position: 'relative',
          width: 40,
          height: 22,
          backgroundColor: checked ? 'var(--color-primary)' : 'var(--bg-tertiary)',
          border: '1px solid',
          borderColor: checked ? 'var(--color-primary)' : 'var(--border-primary)',
          borderRadius: 'var(--radius-full)',
          cursor: disabled ? 'not-allowed' : 'pointer',
          transition: 'var(--transition-base)',
          padding: 0,
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: 2,
            left: checked ? 20 : 2,
            width: 16,
            height: 16,
            backgroundColor: 'var(--color-white)',
            borderRadius: '50%',
            transition: 'var(--transition-base)',
          }}
        />
      </button>
      {label && (
        <span style={{ fontSize: 'var(--font-size-base)', color: 'var(--text-primary)' }}>
          {label}
        </span>
      )}
    </label>
  )
}

// =============================================================================
// CARD
// =============================================================================

export interface CardProps {
  children: ReactNode
  padding?: 'none' | 'sm' | 'md' | 'lg'
  className?: string
  style?: React.CSSProperties
}

const cardPadding = {
  none: 0,
  sm: 'var(--space-2)',
  md: 'var(--space-4)',
  lg: 'var(--space-6)',
}

export function Card({ children, padding = 'md', className, style }: CardProps) {
  return (
    <div
      className={className}
      style={{
        backgroundColor: 'var(--bg-secondary)',
        border: '1px solid var(--border-primary)',
        borderRadius: 'var(--radius-lg)',
        padding: cardPadding[padding],
        ...style,
      }}
    >
      {children}
    </div>
  )
}

// =============================================================================
// ALERT
// =============================================================================

export type AlertVariant = 'info' | 'success' | 'warning' | 'error'

export interface AlertProps {
  variant: AlertVariant
  title?: string
  children: ReactNode
  onClose?: () => void
}

const alertColors: Record<AlertVariant, { bg: string; border: string; text: string }> = {
  info: {
    bg: 'var(--color-info-light)',
    border: 'var(--color-info)',
    text: 'var(--color-info)',
  },
  success: {
    bg: 'var(--color-success-light)',
    border: 'var(--color-success)',
    text: 'var(--color-success)',
  },
  warning: {
    bg: 'var(--color-warning-light)',
    border: 'var(--color-warning)',
    text: 'var(--color-warning)',
  },
  error: {
    bg: 'var(--color-error-light)',
    border: 'var(--color-error)',
    text: 'var(--color-error)',
  },
}

export function Alert({ variant, title, children, onClose }: AlertProps) {
  const colors = alertColors[variant]

  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        gap: 'var(--space-3)',
        padding: 'var(--space-3) var(--space-4)',
        backgroundColor: colors.bg,
        border: `1px solid ${colors.border}`,
        borderRadius: 'var(--radius-md)',
      }}
    >
      <div style={{ flex: 1 }}>
        {title && (
          <div
            style={{
              fontWeight: 'var(--font-weight-semibold)' as any,
              color: colors.text,
              marginBottom: 'var(--space-1)',
            }}
          >
            {title}
          </div>
        )}
        <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-primary)' }}>
          {children}
        </div>
      </div>
      {onClose && (
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: colors.text,
            padding: 0,
            fontSize: '18px',
            lineHeight: 1,
          }}
          aria-label="Close alert"
        >
          ×
        </button>
      )}
    </div>
  )
}

// =============================================================================
// BADGE
// =============================================================================

export type BadgeVariant = 'default' | 'primary' | 'success' | 'warning' | 'error' | 'info'

export interface BadgeProps {
  children: ReactNode
  variant?: BadgeVariant
  size?: 'sm' | 'md'
  dot?: boolean
}

const badgeColors: Record<BadgeVariant, { bg: string; text: string }> = {
  default: { bg: 'var(--bg-tertiary)', text: 'var(--text-secondary)' },
  primary: { bg: 'var(--color-primary-light)', text: 'var(--color-primary)' },
  success: { bg: 'var(--color-success-light)', text: 'var(--color-success)' },
  warning: { bg: 'var(--color-warning-light)', text: 'var(--color-warning)' },
  error: { bg: 'var(--color-error-light)', text: 'var(--color-error)' },
  info: { bg: 'var(--color-info-light)', text: 'var(--color-info)' },
}

export function Badge({ children, variant = 'default', size = 'md', dot }: BadgeProps) {
  const colors = badgeColors[variant]
  const padding = size === 'sm' ? 'var(--space-1) var(--space-2)' : '2px var(--space-2)'
  const fontSize = size === 'sm' ? 'var(--font-size-xs)' : 'var(--font-size-xs)'

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-1)',
        padding,
        fontSize,
        fontWeight: 'var(--font-weight-medium)' as any,
        backgroundColor: colors.bg,
        color: colors.text,
        borderRadius: 'var(--radius-full)',
      }}
    >
      {dot && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            backgroundColor: colors.text,
          }}
        />
      )}
      {children}
    </span>
  )
}

// =============================================================================
// MODAL
// =============================================================================

export interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg'
}

const modalSizes = {
  sm: 320,
  md: 420,
  lg: 560,
}

export function Modal({ open, onClose, title, children, footer, size = 'md' }: ModalProps) {
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        onClose()
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 'var(--z-modal)' as any,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--space-4)',
      }}
    >
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'absolute',
          inset: 0,
          backgroundColor: 'var(--overlay-color)',
          animation: 'fadeIn 0.15s ease-out',
        }}
      />
      {/* Dialog */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? 'modal-title' : undefined}
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: modalSizes[size],
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: 'var(--bg-secondary)',
          border: '1px solid var(--border-primary)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-lg)',
          animation: 'slideUp 0.15s ease-out',
        }}
      >
        {/* Header */}
        {title && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: 'var(--space-4)',
              borderBottom: '1px solid var(--border-primary)',
            }}
          >
            <h2
              id="modal-title"
              style={{
                margin: 0,
                fontSize: 'var(--font-size-lg)',
                fontWeight: 'var(--font-weight-semibold)' as any,
                color: 'var(--text-primary)',
              }}
            >
              {title}
            </h2>
            <button
              onClick={onClose}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--text-secondary)',
                fontSize: '20px',
                lineHeight: 1,
                padding: 'var(--space-1)',
              }}
              aria-label="Close modal"
            >
              ×
            </button>
          </div>
        )}
        {/* Body */}
        <div
          style={{
            flex: 1,
            padding: 'var(--space-4)',
            overflowY: 'auto',
          }}
        >
          {children}
        </div>
        {/* Footer */}
        {footer && (
          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              gap: 'var(--space-2)',
              padding: 'var(--space-4)',
              borderTop: '1px solid var(--border-primary)',
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}

// =============================================================================
// TABLE
// =============================================================================

export interface TableColumn<T> {
  key: string
  header: string
  render?: (item: T, index: number) => ReactNode
  width?: string
  align?: 'left' | 'center' | 'right'
}

export interface TableProps<T> {
  columns: TableColumn<T>[]
  data: T[]
  emptyMessage?: string
  onRowClick?: (item: T, index: number) => void
  rowKey?: (item: T, index: number) => string | number
}

export function Table<T extends Record<string, any>>({
  columns,
  data,
  emptyMessage = 'No data',
  onRowClick,
  rowKey,
}: TableProps<T>) {
  const cellStyle: React.CSSProperties = {
    padding: 'var(--space-3)',
    borderBottom: '1px solid var(--border-primary)',
    textAlign: 'left',
  }

  if (data.length === 0) {
    return <EmptyState message={emptyMessage} />
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: 'var(--font-size-sm)',
        }}
      >
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                style={{
                  ...cellStyle,
                  textAlign: col.align || 'left',
                  width: col.width,
                  fontWeight: 'var(--font-weight-semibold)' as any,
                  color: 'var(--text-secondary)',
                  backgroundColor: 'var(--bg-tertiary)',
                }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((item, index) => (
            <tr
              key={rowKey ? rowKey(item, index) : index}
              onClick={() => onRowClick?.(item, index)}
              style={{
                cursor: onRowClick ? 'pointer' : 'default',
                transition: 'var(--transition-fast)',
              }}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  style={{
                    ...cellStyle,
                    textAlign: col.align || 'left',
                    color: 'var(--text-primary)',
                  }}
                >
                  {col.render ? col.render(item, index) : (item[col.key] as ReactNode)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// =============================================================================
// EMPTY STATE
// =============================================================================

export interface EmptyStateProps {
  icon?: ReactNode
  title?: string
  message: string
  action?: ReactNode
}

export function EmptyState({ icon, title, message, action }: EmptyStateProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--space-8)',
        textAlign: 'center',
      }}
    >
      {icon && (
        <div
          style={{
            marginBottom: 'var(--space-4)',
            color: 'var(--text-muted)',
            fontSize: '48px',
          }}
        >
          {icon}
        </div>
      )}
      {title && (
        <h3
          style={{
            margin: 0,
            marginBottom: 'var(--space-2)',
            fontSize: 'var(--font-size-lg)',
            fontWeight: 'var(--font-weight-semibold)' as any,
            color: 'var(--text-primary)',
          }}
        >
          {title}
        </h3>
      )}
      <p
        style={{
          margin: 0,
          color: 'var(--text-secondary)',
          fontSize: 'var(--font-size-sm)',
        }}
      >
        {message}
      </p>
      {action && <div style={{ marginTop: 'var(--space-4)' }}>{action}</div>}
    </div>
  )
}

// =============================================================================
// CONTAINER
// =============================================================================

export interface ContainerProps {
  children: ReactNode
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | 'full'
  padding?: boolean
  className?: string
  style?: React.CSSProperties
}

const containerMaxWidths = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  full: '100%',
}

export function Container({
  children,
  maxWidth = 'lg',
  padding = true,
  className,
  style,
}: ContainerProps) {
  return (
    <div
      className={className}
      style={{
        width: '100%',
        maxWidth: containerMaxWidths[maxWidth],
        marginLeft: 'auto',
        marginRight: 'auto',
        paddingLeft: padding ? 'var(--space-4)' : 0,
        paddingRight: padding ? 'var(--space-4)' : 0,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

// =============================================================================
// DIVIDER
// =============================================================================

export interface DividerProps {
  orientation?: 'horizontal' | 'vertical'
  spacing?: 'sm' | 'md' | 'lg'
}

const dividerSpacing = {
  sm: 'var(--space-2)',
  md: 'var(--space-4)',
  lg: 'var(--space-6)',
}

export function Divider({ orientation = 'horizontal', spacing = 'md' }: DividerProps) {
  if (orientation === 'vertical') {
    return (
      <div
        style={{
          width: 1,
          backgroundColor: 'var(--border-primary)',
          marginLeft: dividerSpacing[spacing],
          marginRight: dividerSpacing[spacing],
          alignSelf: 'stretch',
        }}
      />
    )
  }

  return (
    <hr
      style={{
        border: 'none',
        height: 1,
        backgroundColor: 'var(--border-primary)',
        marginTop: dividerSpacing[spacing],
        marginBottom: dividerSpacing[spacing],
      }}
    />
  )
}

// =============================================================================
// TABS
// =============================================================================

interface TabsContextValue {
  activeTab: string
  setActiveTab: (id: string) => void
}

const TabsContext = createContext<TabsContextValue | null>(null)

export interface TabsProps {
  children: ReactNode
  defaultTab?: string
  onChange?: (tabId: string) => void
}

export function Tabs({ children, defaultTab, onChange }: TabsProps) {
  const [activeTab, setActiveTab] = useState(defaultTab || '')

  const handleTabChange = (id: string) => {
    setActiveTab(id)
    onChange?.(id)
  }

  return (
    <TabsContext.Provider value={{ activeTab, setActiveTab: handleTabChange }}>
      {children}
    </TabsContext.Provider>
  )
}

export interface TabListProps {
  children: ReactNode
}

export function TabList({ children }: TabListProps) {
  return (
    <div
      role="tablist"
      style={{
        display: 'flex',
        borderBottom: '1px solid var(--border-primary)',
        gap: 'var(--space-1)',
      }}
    >
      {children}
    </div>
  )
}

export interface TabProps {
  id: string
  children: ReactNode
}

export function Tab({ id, children }: TabProps) {
  const context = useContext(TabsContext)
  if (!context) throw new Error('Tab must be used within Tabs')

  const isActive = context.activeTab === id
  const [isHovered, setIsHovered] = useState(false)

  return (
    <button
      role="tab"
      aria-selected={isActive}
      onClick={() => context.setActiveTab(id)}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{
        padding: 'var(--space-3) var(--space-4)',
        fontSize: 'var(--font-size-sm)',
        fontWeight: 'var(--font-weight-medium)' as any,
        color: isActive ? 'var(--color-primary)' : 'var(--text-secondary)',
        backgroundColor: isHovered && !isActive ? 'var(--bg-tertiary)' : 'transparent',
        border: 'none',
        borderBottom: isActive ? '2px solid var(--color-primary)' : '2px solid transparent',
        marginBottom: -1,
        cursor: 'pointer',
        transition: 'var(--transition-fast)',
      }}
    >
      {children}
    </button>
  )
}

export interface TabPanelProps {
  id: string
  children: ReactNode
}

export function TabPanel({ id, children }: TabPanelProps) {
  const context = useContext(TabsContext)
  if (!context) throw new Error('TabPanel must be used within Tabs')

  if (context.activeTab !== id) return null

  return (
    <div role="tabpanel" style={{ padding: 'var(--space-4) 0' }}>
      {children}
    </div>
  )
}

// =============================================================================
// LIST
// =============================================================================

export interface ListProps {
  children: ReactNode
  dividers?: boolean
}

export function List({ children, dividers = true }: ListProps) {
  return (
    <ul
      style={{
        listStyle: 'none',
        margin: 0,
        padding: 0,
      }}
    >
      {React.Children.map(children, (child, index) => (
        <>
          {child}
          {dividers && index < React.Children.count(children) - 1 && (
            <Divider spacing="sm" />
          )}
        </>
      ))}
    </ul>
  )
}

export interface ListItemProps {
  children: ReactNode
  onClick?: () => void
  active?: boolean
}

export function ListItem({ children, onClick, active }: ListItemProps) {
  const [isHovered, setIsHovered] = useState(false)

  return (
    <li
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{
        padding: 'var(--space-3)',
        cursor: onClick ? 'pointer' : 'default',
        backgroundColor: active
          ? 'var(--color-primary-light)'
          : isHovered && onClick
          ? 'var(--bg-tertiary)'
          : 'transparent',
        borderRadius: 'var(--radius-md)',
        transition: 'var(--transition-fast)',
      }}
    >
      {children}
    </li>
  )
}

// =============================================================================
// EXPORTS
// =============================================================================

export type {
  SpinnerProps,
}

// =============================================================================
// LAYOUT KIT — page-level primitives (AppShell, Section, CardGrid, ...)
// The page's structure, gutters, and skeleton states come from these.
// =============================================================================

export {
  AppShell,
  Section,
  CardGrid,
  Toolbar,
  IconBadge,
  StatCard,
  SplitView,
  SkeletonCard,
  SkeletonRow,
} from './layout'
export type {
  AppShellProps,
  SectionProps,
  CardGridProps,
  ToolbarProps,
  IconBadgeProps,
  StatCardProps,
  SplitViewProps,
  SkeletonCardProps,
  SkeletonRowProps,
} from './layout'
