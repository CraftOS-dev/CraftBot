import {
  KeyRound,
  WifiOff,
  Clock,
  CreditCard,
  ShieldAlert,
  ServerCrash,
  AlertCircle,
  AlertTriangle,
  type LucideIcon,
} from 'lucide-react'

export interface ErrorCategoryStyle {
  icon: LucideIcon
  /** CSS custom property name (without var()) carrying this category's accent color. */
  colorVar: string
  label: string
}

// Mirrors ErrorCategory in agent_core/core/errors.py. Single source of truth
// for how a classified error (auth/rate-limit/connection/...) is presented
// across chat bubbles and toasts, instead of every surface picking its own
// icon/color independently.
export const ERROR_CATEGORY_STYLE: Record<string, ErrorCategoryStyle> = {
  auth: { icon: KeyRound, colorVar: '--color-error', label: 'Authentication' },
  credit: { icon: CreditCard, colorVar: '--color-warning', label: 'Billing' },
  rate_limit: { icon: Clock, colorVar: '--color-warning', label: 'Rate limited' },
  quota: { icon: CreditCard, colorVar: '--color-warning', label: 'Quota' },
  model: { icon: AlertCircle, colorVar: '--color-error', label: 'Model' },
  bad_request: { icon: AlertCircle, colorVar: '--color-error', label: 'Request' },
  blocked: { icon: ShieldAlert, colorVar: '--color-error', label: 'Blocked' },
  server: { icon: ServerCrash, colorVar: '--color-error', label: 'Service unavailable' },
  connection: { icon: WifiOff, colorVar: '--color-error', label: 'Connection' },
  config: { icon: KeyRound, colorVar: '--color-error', label: 'Configuration' },
  validation: { icon: AlertCircle, colorVar: '--color-error', label: 'Invalid input' },
  not_found: { icon: AlertCircle, colorVar: '--color-error', label: 'Not found' },
  permission: { icon: ShieldAlert, colorVar: '--color-error', label: 'Permission' },
  internal: { icon: AlertTriangle, colorVar: '--color-error', label: 'Internal error' },
  unknown: { icon: AlertTriangle, colorVar: '--color-error', label: 'Error' },
}

export const DEFAULT_ERROR_CATEGORY_STYLE: ErrorCategoryStyle = {
  icon: AlertTriangle,
  colorVar: '--color-error',
  label: 'Error',
}

export function getErrorCategoryStyle(category?: string | null): ErrorCategoryStyle {
  if (!category) return DEFAULT_ERROR_CATEGORY_STYLE
  return ERROR_CATEGORY_STYLE[category] ?? DEFAULT_ERROR_CATEGORY_STYLE
}
