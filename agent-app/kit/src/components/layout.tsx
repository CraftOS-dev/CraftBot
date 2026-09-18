/**
 * Structural layer (kit 0.6.0) — the app skeleton the good CraftBot apps had
 * to hand-build. These turn a bag of components into a real product: an
 * AppShell with a SidebarNav, a PageHeader per screen, Sections and StatGrids,
 * dense ListRows, and honest EmptyStates.
 *
 * THE RECOMMENDED SHAPE for anything with more than one view:
 *
 *   <AppShell
 *     sidebar={
 *       <SidebarNav
 *         brand={<Brand/>}
 *         active={page}
 *         onSelect={setPage}
 *         sections={[{ items: [{ key: 'home', label: 'Home', icon: <HomeIcon/> }] }]}
 *       />
 *     }
 *   >
 *     <PageHeader title="Customers" meta="128" actions={<Button>New</Button>} />
 *     <StatGrid>
 *       <Stat label="MRR" value="$1,938" tone="good" />
 *     </StatGrid>
 *     <Section title="Recent">
 *       <ListRow primary="Acme" secondary="added today" trailing={<Pill tone="good">Active</Pill>} />
 *     </Section>
 *   </AppShell>
 *
 * Rules distilled from Linear / Stripe / Mercury / Attio / Notion:
 * - hierarchy comes from weight + muted grays, not size jumps; the accent is
 *   used ONLY for interaction and the current thing
 * - color otherwise means STATE: good (green), warn (amber), bad (red)
 * - numbers are tabular and right-aligned; every enum renders as a Pill
 * - empty states get an icon, one headline, one line, one action
 *
 * Icons are always ReactNode (the kit ships no icon dependency): pass an emoji,
 * an inline <svg>, or your app's own icon component. Everything reads --agent-app-*
 * tokens, so light/dark and every style pack keep working.
 */
import type { ReactNode } from 'react';
import { cn } from '../lib/cn.ts';
import { Card, CardContent } from './Card.tsx';

/* ------------------------------------------------------------------ */
/* Tones: the whole status-color language, identical app-wide.         */
/* ------------------------------------------------------------------ */

export type Tone = 'good' | 'warn' | 'bad' | 'info' | 'accent' | 'neutral';

const TONE_TEXT: Record<Tone, string> = {
  good: 'text-emerald-700 dark:text-emerald-400',
  warn: 'text-amber-700 dark:text-amber-400',
  bad: 'text-red-700 dark:text-red-400',
  info: 'text-sky-700 dark:text-sky-400',
  accent: 'text-[var(--agent-app-accent)]',
  neutral: 'text-[var(--agent-app-muted)]',
};

const TONE_BG: Record<Tone, string> = {
  good: 'bg-emerald-500/10',
  warn: 'bg-amber-500/10',
  bad: 'bg-red-500/10',
  info: 'bg-sky-500/10',
  accent: 'bg-[var(--agent-app-accent)]/10',
  neutral: 'bg-[var(--agent-app-border)]/40',
};

const TONE_DOT: Record<Tone, string> = {
  good: 'bg-emerald-500',
  warn: 'bg-amber-500',
  bad: 'bg-red-500',
  info: 'bg-sky-500',
  accent: 'bg-[var(--agent-app-accent)]',
  neutral: 'bg-[var(--agent-app-muted)]',
};

export function Dot({ tone, className }: { tone: Tone; className?: string | undefined }): React.JSX.Element {
  return <span aria-hidden className={cn('inline-block size-1.5 shrink-0 rounded-full', TONE_DOT[tone], className)} />;
}

/** Status pill: dot + label on a tinted background. The one way an enum renders. */
export function Pill({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: ReactNode;
  className?: string | undefined;
}): React.JSX.Element {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium',
        TONE_BG[tone],
        TONE_TEXT[tone],
        className,
      )}
    >
      <Dot tone={tone} />
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Identity chip: deterministic initials avatar (Attio-style row face). */
/* ------------------------------------------------------------------ */

const CHIP_HUES = [
  'bg-orange-500/15 text-orange-700 dark:text-orange-400',
  'bg-sky-500/15 text-sky-700 dark:text-sky-400',
  'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
  'bg-violet-500/15 text-violet-700 dark:text-violet-400',
  'bg-rose-500/15 text-rose-700 dark:text-rose-400',
  'bg-teal-500/15 text-teal-700 dark:text-teal-400',
  'bg-amber-500/15 text-amber-700 dark:text-amber-500',
];

export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter((p) => p !== '');
  const first = parts[0]?.charAt(0) ?? '?';
  const second = parts.length > 1 ? (parts[parts.length - 1]?.charAt(0) ?? '') : '';
  return (first + second).toUpperCase();
}

export function IdentityChip({
  name,
  size = 'md',
  square = false,
  className,
}: {
  name: string;
  size?: 'sm' | 'md' | undefined;
  /** Squares for organizations/things, circles for people. */
  square?: boolean | undefined;
  className?: string | undefined;
}): React.JSX.Element {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  const hue = CHIP_HUES[Math.abs(hash) % CHIP_HUES.length];
  return (
    <span
      aria-hidden
      className={cn(
        'flex shrink-0 select-none items-center justify-center font-semibold',
        size === 'sm' ? 'size-5 text-[9px]' : 'size-7 text-[11px]',
        square ? 'rounded-[var(--agent-app-radius)]' : 'rounded-full',
        hue,
        className,
      )}
    >
      {initialsOf(name)}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Numbers and dates                                                   */
/* ------------------------------------------------------------------ */

export function fmtMoney(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** Signed, colored, tabular money amount (Mercury convention). */
export function MoneyAmount({
  amount,
  kind,
  className,
}: {
  amount: number;
  /** 'in' renders +green, 'out' renders a minus, 'plain' renders neutral. */
  kind: 'in' | 'out' | 'plain';
  className?: string | undefined;
}): React.JSX.Element {
  return (
    <span
      className={cn(
        'whitespace-nowrap text-right tabular-nums',
        kind === 'in' && 'font-medium text-emerald-700 dark:text-emerald-400',
        kind === 'out' && 'text-[var(--agent-app-text)]',
        className,
      )}
    >
      {kind === 'in' ? '+' : kind === 'out' ? '−' : ''}
      {fmtMoney(amount)}
    </span>
  );
}

const DAY_MS = 24 * 3600 * 1000;

/** Relative day phrasing; ISO date in, human phrase out. */
export function relDay(isoDate: string): { label: string; overdue: boolean; days: number } {
  const d = isoDate.slice(0, 10);
  if (d === '') return { label: '', overdue: false, days: 0 };
  const target = new Date(d + 'T00:00:00');
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((target.getTime() - today.getTime()) / DAY_MS);
  if (days === 0) return { label: 'Today', overdue: false, days };
  if (days === 1) return { label: 'Tomorrow', overdue: false, days };
  if (days === -1) return { label: 'Yesterday', overdue: true, days };
  if (days < 0) return { label: `${-days}d overdue`, overdue: true, days };
  if (days < 15) return { label: `in ${days}d`, overdue: false, days };
  return { label: target.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }), overdue: false, days };
}

/** Future-facing relative date; overdue dates go red. */
export function RelDate({ iso, className }: { iso: string; className?: string | undefined }): React.JSX.Element {
  const { label, overdue } = relDay(iso);
  if (label === '') return <span className={cn('text-xs text-[var(--agent-app-muted)]', className)}>-</span>;
  return (
    <span
      className={cn(
        'whitespace-nowrap text-xs tabular-nums',
        overdue ? 'font-medium text-red-600 dark:text-red-400' : 'text-[var(--agent-app-muted)]',
        className,
      )}
    >
      {label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Tiny progress ring (Linear's project donut).                        */
/* ------------------------------------------------------------------ */

export function ProgressRing({
  value,
  size = 16,
  className,
}: {
  /** 0..1 */
  value: number;
  size?: number | undefined;
  className?: string | undefined;
}): React.JSX.Element {
  const r = (size - 3) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={cn('shrink-0 -rotate-90', className)} aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--agent-app-border)" strokeWidth={2} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={v >= 1 ? 'rgb(16 185 129)' : 'var(--agent-app-accent)'}
        strokeWidth={2}
        strokeDasharray={`${c * v} ${c}`}
      />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/* App shell + sidebar navigation                                      */
/* ------------------------------------------------------------------ */

export interface AppShellProps {
  /** The persistent left column, usually a <SidebarNav>. */
  sidebar: ReactNode;
  children: ReactNode;
  /** Content max-width utility (e.g. 'max-w-5xl'). Defaults to 'max-w-6xl'. */
  maxWidth?: string | undefined;
  className?: string | undefined;
}

/** Full-height sidebar + scrolling content frame. The spine of every real app. */
export function AppShell({ sidebar, children, maxWidth = 'max-w-6xl', className }: AppShellProps): React.JSX.Element {
  return (
    <div className={cn('flex min-h-screen bg-[var(--agent-app-bg)] text-[var(--agent-app-text)]', className)}>
      {sidebar}
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8 md:py-8">
        <div className={cn('mx-auto', maxWidth)}>{children}</div>
      </main>
    </div>
  );
}

export interface SidebarNavItem {
  key: string;
  label: string;
  icon?: ReactNode | undefined;
  /** Right-aligned count/badge, e.g. an unread total. */
  badge?: ReactNode | undefined;
}

export interface SidebarNavSection {
  /** Optional uppercase group label. */
  label?: string | undefined;
  items: SidebarNavItem[];
}

export interface SidebarNavProps {
  /** Brand lockup shown at the top (logo + name). */
  brand?: ReactNode | undefined;
  sections: SidebarNavSection[];
  active: string;
  onSelect: (key: string) => void;
  /** Pinned to the bottom (account switcher, sign out, status). */
  footer?: ReactNode | undefined;
  className?: string | undefined;
}

/** Branded, sectioned, icon-led nav column with an accent active state. */
export function SidebarNav({
  brand,
  sections,
  active,
  onSelect,
  footer,
  className,
}: SidebarNavProps): React.JSX.Element {
  return (
    <aside
      className={cn(
        'flex w-60 shrink-0 flex-col border-r border-[var(--agent-app-border)] bg-[var(--agent-app-surface)]',
        className,
      )}
    >
      {brand !== undefined && (
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-[var(--agent-app-border)] px-4">
          {brand}
        </div>
      )}
      <nav className="min-h-0 flex-1 overflow-y-auto p-2">
        {sections.map((section, i) => (
          <div key={i} className={cn(i > 0 && 'mt-4')}>
            {section.label !== undefined && (
              <p className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--agent-app-muted)]">
                {section.label}
              </p>
            )}
            {section.items.map((item) => {
              const isActive = item.key === active;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => onSelect(item.key)}
                  aria-current={isActive ? 'page' : undefined}
                  className={cn(
                    'flex w-full items-center gap-2.5 rounded-[var(--agent-app-radius)] px-2.5 py-1.5 text-sm transition-colors',
                    isActive
                      ? 'bg-[var(--agent-app-selected)] font-medium text-[var(--agent-app-accent)]'
                      : 'text-[var(--agent-app-text)] hover:bg-[var(--agent-app-hover)]',
                  )}
                >
                  {item.icon !== undefined && (
                    <span
                      className={cn(
                        'flex size-4 shrink-0 items-center justify-center',
                        isActive ? 'text-[var(--agent-app-accent)]' : 'text-[var(--agent-app-muted)]',
                      )}
                    >
                      {item.icon}
                    </span>
                  )}
                  <span className="min-w-0 flex-1 truncate text-left">{item.label}</span>
                  {item.badge !== undefined && (
                    <span className="shrink-0 text-xs tabular-nums text-[var(--agent-app-muted)]">{item.badge}</span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </nav>
      {footer !== undefined && (
        <div className="shrink-0 border-t border-[var(--agent-app-border)] p-3">{footer}</div>
      )}
    </aside>
  );
}

/* ------------------------------------------------------------------ */
/* Page scaffolding                                                    */
/* ------------------------------------------------------------------ */

export function PageHeader({
  title,
  meta,
  subtitle,
  actions,
  className,
}: {
  title: string;
  /** Small muted counter next to the title, e.g. "8". */
  meta?: string | undefined;
  subtitle?: string | undefined;
  actions?: ReactNode | undefined;
  className?: string | undefined;
}): React.JSX.Element {
  return (
    <div className={cn('mb-6 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0">
        <div className="flex items-baseline gap-2.5">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {meta !== undefined && <span className="text-sm tabular-nums text-[var(--agent-app-muted)]">{meta}</span>}
        </div>
        {subtitle !== undefined && (
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-[var(--agent-app-muted)]">{subtitle}</p>
        )}
      </div>
      {actions !== undefined && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

/** A titled card with a header bar. The default container for any list/group. */
export function Section({
  title,
  meta,
  actions,
  children,
  className,
  flush = false,
}: {
  title: string;
  meta?: string | undefined;
  actions?: ReactNode | undefined;
  children: ReactNode;
  className?: string | undefined;
  /** flush: no inner padding (for row lists that own their padding). */
  flush?: boolean | undefined;
}): React.JSX.Element {
  return (
    <Card className={cn('overflow-hidden', className)}>
      <div className="flex min-h-10 items-center justify-between gap-3 border-b border-[var(--agent-app-border)] px-4 py-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[13px] font-semibold">{title}</h2>
          {meta !== undefined && <span className="text-xs tabular-nums text-[var(--agent-app-muted)]">{meta}</span>}
        </div>
        {actions !== undefined && <div className="flex items-center gap-1.5">{actions}</div>}
      </div>
      <CardContent className={flush ? 'p-0' : 'p-4'}>{children}</CardContent>
    </Card>
  );
}

/** Slim grouped-list header: label + count (Linear group headers). */
export function GroupHeader({
  label,
  count,
  right,
}: {
  label: string;
  count?: number | undefined;
  right?: ReactNode | undefined;
}): React.JSX.Element {
  return (
    <div className="flex items-center justify-between bg-[var(--agent-app-hover)] px-4 py-1.5">
      <span className="flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--agent-app-muted)]">
        {label}
        {count !== undefined && <span className="font-normal tabular-nums">{count}</span>}
      </span>
      {right}
    </div>
  );
}

/**
 * The canonical row: one clickable object, identity + content + right-side
 * metadata, actions revealed on hover.
 */
export function ListRow({
  leading,
  primary,
  secondary,
  trailing,
  hoverActions,
  onClick,
  className,
}: {
  leading?: ReactNode | undefined;
  primary: ReactNode;
  secondary?: ReactNode | undefined;
  trailing?: ReactNode | undefined;
  hoverActions?: ReactNode | undefined;
  onClick?: (() => void) | undefined;
  className?: string | undefined;
}): React.JSX.Element {
  return (
    <div
      className={cn(
        'group flex min-h-11 items-center gap-3 border-b border-[var(--agent-app-border)] px-4 py-2 transition-colors last:border-0',
        onClick !== undefined && 'cursor-pointer hover:bg-[var(--agent-app-hover)]',
        className,
      )}
      onClick={onClick}
      role={onClick !== undefined ? 'button' : undefined}
      tabIndex={onClick !== undefined ? 0 : undefined}
      onKeyDown={
        onClick !== undefined
          ? (e) => {
              if (e.key === 'Enter') onClick();
            }
          : undefined
      }
    >
      {leading}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{primary}</div>
        {secondary !== undefined && <div className="truncate text-xs text-[var(--agent-app-muted)]">{secondary}</div>}
      </div>
      {trailing !== undefined && <div className="flex shrink-0 items-center gap-3">{trailing}</div>}
      {hoverActions !== undefined && (
        <div
          className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
          onClick={(e) => e.stopPropagation()}
        >
          {hoverActions}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Stat tiles + layout grids                                           */
/* ------------------------------------------------------------------ */

/** KPI tile: label, verdict number, optional delta line and sparkline (Stripe). */
export function Stat({
  label,
  value,
  sub,
  tone,
  spark,
  big = false,
}: {
  label: string;
  value: string;
  /** Small line under the number: delta, goal, hint. */
  sub?: ReactNode | undefined;
  tone?: Tone | undefined;
  spark?: ReactNode | undefined;
  big?: boolean | undefined;
}): React.JSX.Element {
  return (
    <Card>
      <CardContent className="flex items-end justify-between gap-2 px-4 py-3">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wider text-[var(--agent-app-muted)]">{label}</p>
          <p
            className={cn(
              'mt-1 whitespace-nowrap font-semibold tabular-nums tracking-tight',
              big ? 'text-[26px] leading-8' : 'text-lg leading-6',
              tone !== undefined ? TONE_TEXT[tone] : undefined,
            )}
          >
            {value}
          </p>
          {sub !== undefined && <div className="mt-0.5 text-xs text-[var(--agent-app-muted)]">{sub}</div>}
        </div>
        {spark !== undefined && <div className="shrink-0 pb-1 opacity-80">{spark}</div>}
      </CardContent>
    </Card>
  );
}

/** Responsive row of Stat tiles (1 / 2 / 3 columns). */
export function StatGrid({
  children,
  className,
}: {
  children: ReactNode;
  className?: string | undefined;
}): React.JSX.Element {
  return <div className={cn('grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3', className)}>{children}</div>;
}

/** Two-column dashboard grid that collapses to one column on small screens. */
export function DashboardGrid({
  children,
  className,
}: {
  children: ReactNode;
  className?: string | undefined;
}): React.JSX.Element {
  return <div className={cn('grid grid-cols-1 gap-4 lg:grid-cols-2', className)}>{children}</div>;
}

/** Filter/search/action bar above a list. */
export function Toolbar({
  children,
  className,
}: {
  children: ReactNode;
  className?: string | undefined;
}): React.JSX.Element {
  return <div className={cn('mb-4 flex flex-wrap items-center gap-2', className)}>{children}</div>;
}

/* ------------------------------------------------------------------ */
/* Empty state: icon, headline, one line, ONE action.                   */
/* ------------------------------------------------------------------ */

export function EmptyState({
  icon,
  title,
  message,
  action,
  className,
}: {
  /** Any ReactNode: an emoji, an inline <svg>, or your icon component. */
  icon?: ReactNode | undefined;
  title: string;
  message?: string | undefined;
  action?: ReactNode | undefined;
  className?: string | undefined;
}): React.JSX.Element {
  return (
    <div className={cn('flex flex-col items-center gap-2 px-6 py-14 text-center', className)}>
      {icon !== undefined && (
        <span className="mb-1 flex size-10 items-center justify-center rounded-[var(--agent-app-radius)] bg-[var(--agent-app-surface-2)] text-[var(--agent-app-muted)]">
          {icon}
        </span>
      )}
      <p className="text-sm font-semibold">{title}</p>
      {message !== undefined && (
        <p className="max-w-sm text-[13px] leading-relaxed text-[var(--agent-app-muted)]">{message}</p>
      )}
      {action !== undefined && <div className="mt-3">{action}</div>}
    </div>
  );
}
