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
import { ToastHost } from './toast'

// Class names that form the kit's PUBLIC CONTRACT — the dev-mode telemetry
// (agent/devBuildMode.ts) imports these to measure the rendered layout.
// Keep them in sync with the class names used in the styles below.
export const LK_CLASSES = {
  skeleton: 'lk-skel',
  sectionBody: 'lk-section-body',
} as const

// =============================================================================
// AppShell — full-page frame: gutters, rhythm, overflow discipline.
// Fills its container by default; readingWidth opts into the
// --measure-reading token cap; fullBleed removes the gutters entirely.
// =============================================================================

export interface AppShellProps {
  /** Optional left sidebar (fixed width, hidden on narrow screens). */
  sidebar?: ReactNode
  /** Page content — typically a stack of <Section>s. */
  children: ReactNode
  /**
   * OPT-IN reading-width cap (the --measure-reading design token). By
   * default the app FILLS its container (the Living UI tab) — set this
   * only for long-form reading content where full-width lines hurt
   * readability. Ignored when fullBleed.
   */
  readingWidth?: boolean
  /**
   * Edge-to-edge mode for board/canvas/map/calendar apps: no gutters at
   * all — the content owns the whole viewport and paints its own
   * background. The default (no props) fills the container WITH gutters.
   */
  fullBleed?: boolean
}

export function AppShell({ sidebar, children, readingWidth = false, fullBleed = false }: AppShellProps) {
  const shellClass = fullBleed
    ? 'lk-shell lk-shell-bleed'
    : readingWidth
      ? 'lk-shell lk-shell-reading'
      : 'lk-shell'
  return (
    <div className={shellClass}>
      <div className="lk-shell-body">
        {sidebar && <aside className="lk-shell-sidebar">{sidebar}</aside>}
        <main className="lk-shell-main">{children}</main>
      </div>
      <ToastHost />
      <style>{`
        .lk-shell {
          min-height: 100vh;
          display: flex;
          flex-direction: column;
          background-color: var(--bg-primary);
          background-image: var(--page-backdrop);
          background-attachment: fixed;
          background-size: cover;
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
        .lk-shell-reading .lk-shell-body {
          max-width: var(--measure-reading);
        }
        .lk-shell-bleed .lk-shell-body {
          max-width: none;
          padding: 0;
          gap: 0;
          align-items: stretch;
        }
        .lk-shell-bleed .lk-shell-main {
          gap: 0;
        }
        .lk-shell-bleed .lk-shell-main > * {
          flex: 1;
          min-height: 0;
        }
        .lk-shell-sidebar {
          flex: 0 0 240px;
          position: sticky;
          top: var(--space-6);
          min-width: 0;
        }
        .lk-shell-bleed .lk-shell-sidebar {
          position: sticky;
          top: 0;
          align-self: stretch;
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
          .lk-shell-bleed .lk-shell-body {
            padding: 0;
            gap: 0;
          }
          .lk-shell-sidebar { position: static; flex: none; width: 100%; }
          .lk-shell-main { gap: var(--space-6); }
          .lk-shell-bleed .lk-shell-main { gap: 0; }
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
  /** Color token or css color. Default is NEUTRAL — pass semantic colors
   * (var(--color-info), var(--color-success), …) to differentiate stats;
   * don't make every badge the primary accent. */
  color?: string
  /** Diameter in px (default 36). */
  size?: number
}

/** Token names agents naturally write ("warning") resolve to their CSS
 * variables — a bare token name would otherwise be an invalid color and
 * silently render untinted. */
function resolveAccent(color: string): string {
  return ['primary', 'success', 'warning', 'error', 'info'].includes(color)
    ? `var(--color-${color})`
    : color
}

export function IconBadge({ icon, color = 'var(--text-secondary)', size = 36 }: IconBadgeProps) {
  color = resolveAccent(color)
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
          backdrop-filter: var(--surface-backdrop);
          border: 1px solid var(--border-primary);
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

/**
 * ALL skeletons are ADAPTIVE: they size from their container (width 100%,
 * aspect-ratio or em heights), never from px props — a skeleton can never
 * overflow its parent. Adjacent skeletons space themselves automatically;
 * use <SkeletonStack> to group mixed shapes with consistent rhythm.
 *
 * The wireframe vocabulary (Phase 1.5 uses ONLY these — never hand-made
 * shimmer divs, inline styles, or px sizes):
 *   SkeletonBox     plain rectangle   (ratio = width/height proportion)
 *   SkeletonCircle  circle            (sm | md | lg, em-scaled)
 *   SkeletonText    paragraph lines   (staggered widths)
 *   SkeletonChip    pill row          (filters/tags placeholder)
 *   SkeletonCard    media card        (aspect media + text lines)
 *   SkeletonRow     list rows
 *   SkeletonStack   vertical group with kit spacing
 */

export interface SkeletonBoxProps {
  /** How many boxes (default 1). */
  count?: number
  /** Width/height proportion, e.g. 3 = wide strip, 1 = square (default 3). */
  ratio?: number
}

export function SkeletonBox({ count = 1, ratio = 3 }: SkeletonBoxProps) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="lk-skel lk-skel-box"
          style={{ aspectRatio: `${ratio}` } as CSSProperties}
        />
      ))}
      <SkeletonStyles />
    </>
  )
}

export interface SkeletonCircleProps {
  count?: number
  /** Diameter, type-scaled: 'sm' (avatar) | 'md' | 'lg' (default 'md'). */
  size?: 'sm' | 'md' | 'lg'
}

export function SkeletonCircle({ count = 1, size = 'md' }: SkeletonCircleProps) {
  return (
    <div className="lk-skel-circles">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={`lk-skel lk-skel-circle lk-skel-circle-${size}`} />
      ))}
      <SkeletonStyles />
    </div>
  )
}

export interface SkeletonTextProps {
  /** Number of text lines (default 3). Widths stagger automatically. */
  lines?: number
}

export function SkeletonText({ lines = 3 }: SkeletonTextProps) {
  const widths = ['92%', '78%', '85%', '64%', '88%', '71%']
  return (
    <div className="lk-skel-text">
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="lk-skel lk-skel-textline"
          style={{ width: widths[i % widths.length] }}
        />
      ))}
      <SkeletonStyles />
    </div>
  )
}

export interface SkeletonChipProps {
  /** Number of pills (default 3). */
  count?: number
}

export function SkeletonChip({ count = 3 }: SkeletonChipProps) {
  return (
    <div className="lk-skel-chips">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="lk-skel lk-skel-chip" />
      ))}
      <SkeletonStyles />
    </div>
  )
}

export interface SkeletonCardProps {
  /** How many placeholder cards to render (default 1). */
  count?: number
  /** Text lines under the media block (default 2). */
  lines?: number
  /** Render the media block (default true). */
  media?: boolean
}

export function SkeletonCard({ count = 1, lines = 2, media = true }: SkeletonCardProps) {
  const widths = ['72%', '48%', '84%', '56%']
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="lk-skel-card">
          {media && <div className="lk-skel lk-skel-media" />}
          {Array.from({ length: lines }, (_, j) => (
            <div
              key={j}
              className="lk-skel lk-skel-line"
              style={{ width: widths[j % widths.length] }}
            />
          ))}
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

export interface SkeletonStackProps {
  /** Mixed skeleton shapes, stacked with consistent kit spacing. */
  children: ReactNode
}

export function SkeletonStack({ children }: SkeletonStackProps) {
  return (
    <div className="lk-skel-stack">
      {children}
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
        max-width: 100%;
        min-width: 0;
        box-sizing: border-box;
      }
      .lk-skel::after {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(
          90deg,
          transparent 0%,
          var(--shimmer) 50%,
          transparent 100%
        );
        animation: lkShimmer 1.6s ease-in-out infinite;
      }
      @keyframes lkShimmer {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(100%); }
      }
      /* Adjacent skeletons never stick together (containers with their own
         gap zero this out below). */
      .lk-skel + .lk-skel,
      .lk-skel + .lk-skel-card,
      .lk-skel-card + .lk-skel,
      .lk-skel-card + .lk-skel-card {
        margin-top: var(--space-3);
      }
      .lk-skel-rows > .lk-skel + .lk-skel,
      .lk-skel-text > .lk-skel + .lk-skel,
      .lk-skel-chips > .lk-skel + .lk-skel,
      .lk-skel-circles > .lk-skel + .lk-skel,
      .lk-skel-stack > .lk-skel + .lk-skel,
      .lk-skel-stack > .lk-skel + .lk-skel-card,
      .lk-skel-stack > .lk-skel-card + .lk-skel,
      .lk-skel-stack > .lk-skel-card + .lk-skel-card {
        margin-top: 0;
      }
      .lk-skel-box { width: 100%; }
      .lk-skel-circles {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        flex-wrap: wrap;
        min-width: 0;
      }
      .lk-skel-circle { border-radius: var(--radius-full); flex-shrink: 0; }
      .lk-skel-circle-sm { width: 2em; height: 2em; }
      .lk-skel-circle-md { width: 3em; height: 3em; }
      .lk-skel-circle-lg { width: 4.5em; height: 4.5em; }
      .lk-skel-text {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        min-width: 0;
      }
      .lk-skel-textline { height: 0.9em; }
      .lk-skel-chips {
        display: flex;
        gap: var(--space-2);
        flex-wrap: wrap;
        min-width: 0;
      }
      .lk-skel-chip { height: 1.8em; width: 5.5em; max-width: 30%; }
      .lk-skel-card {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        padding: var(--space-4);
        background: var(--bg-secondary);
        backdrop-filter: var(--surface-backdrop);
        border: 1px solid var(--border-primary);
        border-radius: var(--radius-lg);
        overflow: hidden;
        max-width: 100%;
        min-width: 0;
        box-sizing: border-box;
      }
      .lk-skel-media { width: 100%; aspect-ratio: 16 / 9; }
      .lk-skel-line { height: 0.8em; flex-shrink: 0; }
      .lk-skel-rows {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        min-width: 0;
      }
      .lk-skel-row { height: 2.75em; }
      .lk-skel-stack {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        min-width: 0;
      }
    `}</style>
  )
}
