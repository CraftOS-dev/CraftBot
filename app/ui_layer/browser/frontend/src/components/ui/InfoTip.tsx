import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Info } from 'lucide-react'
import styles from './InfoTip.module.css'

export interface InfoTipProps {
  /** Accessible name of the ⓘ trigger, e.g. "About cron jobs". */
  label: string
  /** Bold first line of the tooltip. */
  title?: string
  /** One paragraph per entry. */
  lines: string[]
}

/**
 * An ⓘ icon that explains more on hover or keyboard focus, in the same look
 * as the Main chat tooltip in the sidebar. The tooltip is portalled to
 * <body> so a card's edges can't clip it; it opens below the icon, flips
 * above it when there's no room, and shifts left at the window's edge.
 */
export function InfoTip({ label, title, lines }: InfoTipProps) {
  const [anchor, setAnchor] = useState<DOMRect | null>(null)
  const tooltipId = useId()
  const show = (el: HTMLElement) => setAnchor(el.getBoundingClientRect())
  const hide = () => setAnchor(null)

  return (
    <span
      className={styles.trigger}
      tabIndex={0}
      aria-label={label}
      aria-describedby={anchor ? tooltipId : undefined}
      onMouseEnter={e => show(e.currentTarget)}
      onMouseLeave={hide}
      onFocus={e => show(e.currentTarget)}
      onBlur={hide}
    >
      <Info size={13} />
      {anchor && (
        <TipPopover anchor={anchor} id={tooltipId}>
          {title && <strong>{title}</strong>}
          {lines.map((line, i) => (
            <span key={i} className={styles.line}>{line}</span>
          ))}
        </TipPopover>
      )}
    </span>
  )
}

function TipPopover({ anchor, id, children }: { anchor: DOMRect; id: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    const margin = 8
    const below = anchor.bottom + 4
    const top = below + height <= window.innerHeight - margin
      ? below
      : Math.max(margin, anchor.top - 4 - height)
    const left = Math.max(margin, Math.min(anchor.left, window.innerWidth - margin - width))
    setPos({ top, left })
  }, [anchor])

  return createPortal(
    <div
      ref={ref}
      id={id}
      className={styles.tooltip}
      role="tooltip"
      // First pass renders hidden to measure; the layout effect places it
      // before paint.
      style={pos ?? { top: 0, left: 0, visibility: 'hidden' }}
    >
      {children}
    </div>,
    document.body,
  )
}
