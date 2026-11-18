import React from 'react'
import * as LucideIcons from 'lucide-react'
import { Globe } from 'lucide-react'
import {
  Gmail,
  Slack,
  Notion,
  GitHubDark,
  GitHubLight,
  Discord,
  LinkedIn,
  Stripe,
  Twitter,
  Telegram,
  WhatsApp,
  GoogleCalendar,
  GoogleDrive,
  YouTube,
  MicrosoftOutlook,
  PostHog,
  Supabase,
} from '@ridemountainpig/svgl-react'
import { useTheme } from '../../contexts/ThemeContext'
import styles from './IntegrationIcon.module.css'

// An integration's brand logo: the Settings integration list and the chat's
// action rows (an integration's action shows its logo) render the same one.

// Full-color SVGL brand components (@ridemountainpig/svgl-react) keyed by
// integration id. GitHub is monochrome and handled separately (theme-matched
// light/dark variant), so it is not in this map.
type SvglIcon = (props: React.SVGProps<SVGSVGElement>) => React.JSX.Element
const SVGL_BY_ID: Record<string, SvglIcon> = {
  gmail: Gmail,
  slack: Slack,
  notion: Notion,
  discord: Discord,
  linkedin: LinkedIn,
  stripe: Stripe,
  twitter: Twitter,
  telegram_bot: Telegram,
  telegram_user: Telegram,
  whatsapp_web: WhatsApp,
  whatsapp_business: WhatsApp,
  google_calendar: GoogleCalendar,
  google_drive: GoogleDrive,
  google_youtube: YouTube,
  outlook: MicrosoftOutlook,
  posthog: PostHog,
  supabase: Supabase,
}

// Integration icon component. Lookup order:
//   1. SVGL brand component keyed by integration id (the standard for every
//      brand SVGL ships; GitHub resolves to a theme-matched variant).
//   2. Hand-crafted brand SVG for the brands SVGL doesn't carry
//      (jira, hubspot, line, lark, google_docs), keyed by the backend ``icon``.
//   3. Lucide icon by the backend ``icon`` name (e.g. Outlook's "Inbox").
//   4. Generic globe fallback.
export const IntegrationIcon = ({ id, icon, size = 20 }: { id: string; icon?: string; size?: number }) => {
  const { theme } = useTheme()

  // 1. SVGL. GitHub's mark is monochrome: pick the variant that shows against
  //    the active theme (GitHubDark = white mark for dark UI, GitHubLight = dark
  //    mark for light UI).
  const svgl: SvglIcon | undefined =
    id === 'github'
      ? (theme === 'dark' ? GitHubDark : GitHubLight)
      : SVGL_BY_ID[id]
  if (svgl) {
    const Logo = svgl
    return (
      <span className={styles.logo}>
        <Logo width={size} height={size} />
      </span>
    )
  }

  // 2. Hand-crafted brand SVGs — only for brands SVGL doesn't have.
  const icons: Record<string, React.ReactNode> = {
    google_docs: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M5 2h9l5 5v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" fill="#4285F4"/>
        <path d="M14 2v5h5l-5-5z" fill="#A1C2FA"/>
        <rect x="6" y="11" width="12" height="1.2" rx="0.6" fill="#fff"/>
        <rect x="6" y="14" width="12" height="1.2" rx="0.6" fill="#fff"/>
        <rect x="6" y="17" width="9" height="1.2" rx="0.6" fill="#fff"/>
      </svg>
    ),
    line: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="#06C755">
        <path d="M19.365 9.863c.349 0 .63.285.63.631 0 .345-.281.63-.63.63H17.61v1.125h1.755c.349 0 .63.283.63.63 0 .344-.281.629-.63.629h-2.386c-.345 0-.627-.285-.627-.629V8.108c0-.345.282-.63.63-.63h2.386c.346 0 .627.285.627.63 0 .349-.281.63-.63.63H17.61v1.125h1.755zm-3.855 3.016c0 .27-.174.51-.432.596-.064.021-.133.031-.199.031-.211 0-.391-.09-.51-.25l-2.443-3.317v2.94c0 .344-.279.629-.631.629-.346 0-.626-.285-.626-.629V8.108c0-.27.173-.51.43-.595.06-.023.136-.033.194-.033.195 0 .375.104.495.254l2.462 3.33V8.108c0-.345.282-.63.63-.63.345 0 .63.285.63.63v4.771zm-5.741 0c0 .344-.282.629-.631.629-.345 0-.627-.285-.627-.629V8.108c0-.345.282-.63.63-.63.346 0 .628.285.628.63v4.771zm-2.466.629H4.917c-.345 0-.63-.285-.63-.629V8.108c0-.345.285-.63.63-.63.348 0 .63.285.63.63v4.141h1.756c.348 0 .629.283.629.63 0 .344-.282.629-.629.629M24 10.314C24 4.943 18.615.572 12 .572S0 4.943 0 10.314c0 4.811 4.27 8.842 10.035 9.608.391.082.923.258 1.058.59.12.301.079.766.038 1.08l-.164 1.02c-.045.301-.24 1.186 1.049.645 1.291-.539 6.916-4.078 9.436-6.975C23.176 14.393 24 12.458 24 10.314"/>
      </svg>
    ),
    lark: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <defs>
          <linearGradient id="larkGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#00D6B9"/>
            <stop offset="50%" stopColor="#00B8E0"/>
            <stop offset="100%" stopColor="#3370FF"/>
          </linearGradient>
        </defs>
        <rect x="2" y="2" width="20" height="20" rx="4.5" fill="url(#larkGrad)"/>
        <path d="M7.5 9.2c0-.66.54-1.2 1.2-1.2h6.4c.66 0 1.2.54 1.2 1.2v2.4c0 1.66-1.34 3-3 3H10.6l-2.6 2.2c-.3.25-.5.05-.5-.3v-7.3z" fill="#fff"/>
      </svg>
    ),
    jira: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="#0052CC">
        <path d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005z"/>
        <path d="M6.348 6.349H-5.224a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057a5.215 5.215 0 0 0 5.215 5.215V7.354a1.005 1.005 0 0 0-1.005-1.005z" transform="translate(5.224)"/>
        <path d="M11.571 0H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 12.487V1.005A1.005 1.005 0 0 0 11.571 0z" transform="translate(.348 1.164)"/>
      </svg>
    ),
    hubspot: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        {/* Connector lines end on the ring stroke centerline (r=5.5 from ring center),
            so the ring draws OVER the line end and the hole stays clean. */}
        <line x1="4" y1="4" x2="11.1" y2="11.1" stroke="#FF7A59" strokeWidth="2.5" strokeLinecap="round"/>
        <line x1="17.5" y1="3" x2="17.5" y2="10.1" stroke="#FF7A59" strokeWidth="2.5" strokeLinecap="round"/>
        <line x1="8" y1="21.5" x2="11" y2="18.7" stroke="#FF7A59" strokeWidth="2.5" strokeLinecap="round"/>
        {/* Main ring (donut) — fill="none" + stroke creates the visible hole */}
        <circle cx="15" cy="15" r="5.5" stroke="#FF7A59" strokeWidth="2.5" fill="none"/>
        {/* Satellite dots */}
        <circle cx="4" cy="4" r="2.5" fill="#FF7A59"/>
        <circle cx="17.5" cy="3" r="2.2" fill="#FF7A59"/>
        <circle cx="8" cy="21.5" r="2.2" fill="#FF7A59"/>
      </svg>
    ),
  }
  if (icon && icons[icon]) {
    return <span className={styles.logo}>{icons[icon]}</span>
  }
  if (icons[id]) {
    return <span className={styles.logo}>{icons[id]}</span>
  }

  // 3. Lucide fallback for non-brand icons (e.g. Outlook's "Inbox").
  if (icon) {
    const lucideMap = LucideIcons as unknown as Record<string, React.ComponentType<{ size?: number }>>
    const LucideIcon = lucideMap[icon]
    if (LucideIcon) {
      return <span className={styles.logo}><LucideIcon size={size} /></span>
    }
  }

  // 4. Generic fallback.
  return <span className={styles.logo}><Globe size={size} /></span>
}
