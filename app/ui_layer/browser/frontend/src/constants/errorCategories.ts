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
  /** i18n key (in the `common` namespace) for this category's display label. */
  labelKey: string
}

// Mirrors ErrorCategory in agent_core/core/errors.py. Single source of truth
// for how a classified error (auth/rate-limit/connection/...) is presented
// across chat bubbles and toasts, instead of every surface picking its own
// icon/color independently. Labels are i18n keys; render with t(style.labelKey).
export const ERROR_CATEGORY_STYLE: Record<string, ErrorCategoryStyle> = {
  auth: { icon: KeyRound, colorVar: '--color-error', labelKey: 'common:errorCategory.auth' },
  credit: { icon: CreditCard, colorVar: '--color-warning', labelKey: 'common:errorCategory.credit' },
  rate_limit: { icon: Clock, colorVar: '--color-warning', labelKey: 'common:errorCategory.rateLimit' },
  quota: { icon: CreditCard, colorVar: '--color-warning', labelKey: 'common:errorCategory.quota' },
  model: { icon: AlertCircle, colorVar: '--color-error', labelKey: 'common:errorCategory.model' },
  bad_request: { icon: AlertCircle, colorVar: '--color-error', labelKey: 'common:errorCategory.badRequest' },
  blocked: { icon: ShieldAlert, colorVar: '--color-error', labelKey: 'common:errorCategory.blocked' },
  server: { icon: ServerCrash, colorVar: '--color-error', labelKey: 'common:errorCategory.server' },
  connection: { icon: WifiOff, colorVar: '--color-error', labelKey: 'common:errorCategory.connection' },
  config: { icon: KeyRound, colorVar: '--color-error', labelKey: 'common:errorCategory.config' },
  validation: { icon: AlertCircle, colorVar: '--color-error', labelKey: 'common:errorCategory.validation' },
  not_found: { icon: AlertCircle, colorVar: '--color-error', labelKey: 'common:errorCategory.notFound' },
  permission: { icon: ShieldAlert, colorVar: '--color-error', labelKey: 'common:errorCategory.permission' },
  internal: { icon: AlertTriangle, colorVar: '--color-error', labelKey: 'common:errorCategory.internal' },
  unknown: { icon: AlertTriangle, colorVar: '--color-error', labelKey: 'common:errorCategory.unknown' },
}

export const DEFAULT_ERROR_CATEGORY_STYLE: ErrorCategoryStyle = {
  icon: AlertTriangle,
  colorVar: '--color-error',
  labelKey: 'common:errorCategory.unknown',
}

export function getErrorCategoryStyle(category?: string | null): ErrorCategoryStyle {
  if (!category) return DEFAULT_ERROR_CATEGORY_STYLE
  return ERROR_CATEGORY_STYLE[category] ?? DEFAULT_ERROR_CATEGORY_STYLE
}
