/**
 * Living UI Layout Kit — pre-styled page-level primitives.
 *
 * The page's visual quality (gutters, max-width, vertical rhythm, section
 * spacing, overflow discipline, skeleton states) is OWNED BY THIS KIT, not
 * hand-written per app. Build every Living UI page by assembling these:
 *
 *   <AppShell>
 *     <Section title="Categories">…</Section>
 *     <Section title="Articles" actions={<Button size="sm">Refresh</Button>}>
 *       <CardGrid>{cards or <SkeletonCard count={6} />}</CardGrid>
 *     </Section>
 *   </AppShell>
 *
 * Rules the kit enforces by construction:
 *  - content never touches the viewport edge (shell gutters + max-width)
 *  - nothing overflows horizontally (shell clips; text ellipsizes)
 *  - every action lives in exactly one Section's `actions` slot
 *  - loading/empty phases look intentional (Skeleton*, EmptyState)
 *
 * System-managed — import from './components/ui', never modify.
 */

import type { CSSProperties, ReactNode } from 'react'

// Class names that form the kit's PUBLIC CONTRACT — the dev-mode telemetry
// (agent/devBuildMode.ts) imports these to measure the rendered layout.
// Keep them in sync with the class names used in the styles below.
export const LK_CLASSES = {
  skeleton: 'lk-skel',
  sectionBody: 'lk-section-body',
} as const

// =============================================================================
// AppShell — full-page frame: gutters, max-width, rhythm, overflow discipline
// =============================================================================

export interface AppShellProps {
  /** Optional left sidebar (fixed width, hidden on narrow screens). */
  sidebar?: ReactNode
  /** Page content — typically a stack of <Section>s. */
  children: ReactNode
  /** Content max width in px (default 1200). */
  maxWidth?: number
}

export function AppShell({ sidebar, children, maxWidth = 1200 }: AppShellProps) {
  return (
    <div className="lk-shell">
      <div className="lk-shell-body" style={{ maxWidth: `${maxWidth}px` }}>
        {sidebar && <aside className="lk-shell-sidebar">{sidebar}</aside>}
        <main className="lk-shell-main">{children}</main>
      </div>
      <style>{`
        .lk-shell {
          min-height: 100vh;
          display: flex;
          flex-direction: column;
          background: var(--bg-primary);
          color: var(--text-primary);
          overflow-x: hidden;
        }
        .lk-shell-body {
          width: 100%;
          margin: 0 auto;
          padding: var(--space-6) var(--space-6) var(--space-12);
          display: flex;
          gap: var(--space-6);
          align-items: flex-start;
          flex: 1;
          min-width: 0;
        }
        .lk-shell-sidebar {
          flex: 0 0 240px;
          position: sticky;
          top: var(--space-6);
          min-width: 0;
        }
        .lk-shell-main {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          gap: var(--space-8);
        }
        @media (max-width: 768px) {
          .lk-shell-body {
            flex-direction: column;
            padding: var(--space-4) var(--space-4) var(--space-8);
            gap: var(--space-4);
          }
          .lk-shell-sidebar { position: static; flex: none; width: 100%; }
          .lk-shell-main { gap: var(--space-6); }
        }
      `}</style>
    </div>
  )
}

// =============================================================================
// Section — titled content block with consistent spacing + its own actions
// =============================================================================

export interface SectionProps {
  title?: ReactNode
  /** Small text right of the title (counts, hints). */
  meta?: ReactNode
  /** Section-scoped actions (buttons/filters for THIS section only). */
  actions?: ReactNode
  children: ReactNode
}

export function Section({ title, meta, actions, children }: SectionProps) {
  return (
    <section className="lk-section">
      {(title || actions || meta) && (
        <div className="lk-section-head">
          <div className="lk-section-titles">
            {title && <h2 className="lk-section-title">{title}</h2>}
            {meta && <span className="lk-section-meta">{meta}</span>}
          </div>
          {actions && <div className="lk-section-actions">{actions}</div>}
        </div>
      )}
      <div className="lk-section-body">{children}</div>
      <style>{`
        .lk-section { min-width: 0; }
        .lk-section-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: var(--space-4);
          margin-bottom: var(--space-4);
          min-width: 0;
        }
        .lk-section-titles {
          display: flex;
          align-items: baseline;
          gap: var(--space-3);
          min-width: 0;
        }
        .lk-section-title {
          margin: 0;
          font-size: var(--font-size-xl);
          font-weight: var(--font-weight-semibold);
          white-space: nowrap;
        }
        .lk-section-meta {
          font-size: var(--font-size-sm);
          color: var(--text-muted);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .lk-section-actions {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          flex-shrink: 0;
        }
        .lk-section-body { min-width: 0; }
      `}</style>
    </section>
  )
}

// =============================================================================
// CardGrid — responsive card layout with correct gaps
// =============================================================================

export interface CardGridProps {
  children: ReactNode
  /** Minimum card width in px before wrapping (default 260). */
  minWidth?: number
}

export function CardGrid({ children, minWidth = 260 }: CardGridProps) {
  return (
    <div
      className="lk-cardgrid"
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${minWidth}px, 1fr))` } as CSSProperties}
    >
      {children}
      <style>{`
        .lk-cardgrid {
          display: grid;
          gap: var(--space-4);
          min-width: 0;
        }
      `}</style>
    </div>
  )
}

// =============================================================================
// Toolbar — one horizontal row of controls with correct gaps and wrapping
// =============================================================================

export interface ToolbarProps {
  children: ReactNode
  /** Push a trailing group to the right edge. */
  end?: ReactNode
}

export function Toolbar({ children, end }: ToolbarProps) {
  return (
    <div className="lk-toolbar">
      <div className="lk-toolbar-main">{children}</div>
      {end && <div className="lk-toolbar-end">{end}</div>}
      <style>{`
        .lk-toolbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: var(--space-3);
          flex-wrap: wrap;
          min-width: 0;
        }
        .lk-toolbar-main {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          flex-wrap: wrap;
          min-width: 0;
          flex: 1;
        }
        .lk-toolbar-end {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          flex-shrink: 0;
        }
      `}</style>
    </div>
  )
}

// =============================================================================
// IconBadge — colored icon holder; the cheapest way to make UI non-text-only
// =============================================================================

export interface IconBadgeProps {
  /** A lucide-react icon element, e.g. <Newspaper size={18} />. */
  icon: ReactNode
  /** Accent color token or css color (default: var(--color-primary)). */
  color?: string
  /** Diameter in px (default 36). */
  size?: number
}

export function IconBadge({ icon, color = 'var(--color-primary)', size = 36 }: IconBadgeProps) {
  return (
    <span
      className="lk-iconbadge"
      style={{
        width: `${size}px`,
        height: `${size}px`,
        color,
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
      } as CSSProperties}
    >
      {icon}
      <style>{`
        .lk-iconbadge {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border-radius: var(--radius-md);
          flex-shrink: 0;
        }
      `}</style>
    </span>
  )
}

// =============================================================================
// StatCard — icon + big value + label; dashboards stop being walls of text
// =============================================================================

export interface StatCardProps {
  /** A lucide-react icon element. */
  icon?: ReactNode
  value: ReactNode
  label: ReactNode
  /** Accent color for the icon badge. */
  color?: string
}

export function StatCard({ icon, value, label, color }: StatCardProps) {
  return (
    <div className="lk-statcard">
      {icon && <IconBadge icon={icon} color={color} />}
      <div className="lk-statcard-text">
        <div className="lk-statcard-value">{value}</div>
        <div className="lk-statcard-label">{label}</div>
      </div>
      <style>{`
        .lk-statcard {
          display: flex;
          align-items: center;
          gap: var(--space-3);
          padding: var(--space-4);
          background: var(--bg-secondary);
          border: 1px solid var(--border-color, var(--color-gray-800));
          border-radius: var(--radius-lg);
          min-width: 0;
        }
        .lk-statcard-text { min-width: 0; }
        .lk-statcard-value {
          font-size: var(--font-size-2xl);
          font-weight: var(--font-weight-bold);
          line-height: 1.2;
          color: var(--text-primary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .lk-statcard-label {
          font-size: var(--font-size-sm);
          color: var(--text-secondary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      `}</style>
    </div>
  )
}

// =============================================================================
// SplitView — main content + fixed-width aside, collapses on narrow screens
// =============================================================================

export interface SplitViewProps {
  children: ReactNode
  aside: ReactNode
  /** Aside width in px (default 320). */
  asideWidth?: number
}

export function SplitView({ children, aside, asideWidth = 320 }: SplitViewProps) {
  return (
    <div className="lk-splitview">
      <div className="lk-splitview-main">{children}</div>
      <div className="lk-splitview-aside" style={{ flexBasis: `${asideWidth}px` }}>
        {aside}
      </div>
      <style>{`
        .lk-splitview {
          display: flex;
          gap: var(--space-4);
          align-items: flex-start;
          min-width: 0;
        }
        .lk-splitview-main { flex: 1; min-width: 0; }
        .lk-splitview-aside { flex-shrink: 0; min-width: 0; }
        @media (max-width: 768px) {
          .lk-splitview { flex-direction: column; }
          .lk-splitview-aside { flex-basis: auto !important; width: 100%; }
        }
      `}</style>
    </div>
  )
}

// =============================================================================
// Skeletons — intentional shimmer placeholders for wireframes/loading
// (For the no-data pattern use the existing <EmptyState> preset from index.)
// =============================================================================

export interface SkeletonCardProps {
  /** How many placeholder cards to render (default 1). */
  count?: number
  /** Card height in px (default 180). */
  height?: number
}

export function SkeletonCard({ count = 1, height = 180 }: SkeletonCardProps) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="lk-skel-card" style={{ height: `${height}px` }}>
          <div className="lk-skel lk-skel-media" />
          <div className="lk-skel lk-skel-line" style={{ width: '72%' }} />
          <div className="lk-skel lk-skel-line" style={{ width: '48%' }} />
        </div>
      ))}
      <SkeletonStyles />
    </>
  )
}

export interface SkeletonRowProps {
  count?: number
}

export function SkeletonRow({ count = 3 }: SkeletonRowProps) {
  return (
    <div className="lk-skel-rows">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="lk-skel lk-skel-row" />
      ))}
      <SkeletonStyles />
    </div>
  )
}

function SkeletonStyles() {
  return (
    <style>{`
      .lk-skel {
        position: relative;
        overflow: hidden;
        background: var(--bg-tertiary);
        border-radius: var(--radius-md);
      }
      .lk-skel::after {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(
          90deg,
          transparent 0%,
          rgba(255, 255, 255, 0.06) 50%,
          transparent 100%
        );
        animation: lkShimmer 1.6s ease-in-out infinite;
      }
      @keyframes lkShimmer {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(100%); }
      }
      .lk-skel-card {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        padding: var(--space-4);
        background: var(--bg-secondary);
        border: 1px solid var(--border-color, var(--color-gray-800));
        border-radius: var(--radius-lg);
        overflow: hidden;
      }
      .lk-skel-media { flex: 1; min-height: 48px; }
      .lk-skel-line { height: 12px; flex-shrink: 0; }
      .lk-skel-rows {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .lk-skel-row { height: 44px; }
    `}</style>
  )
}
