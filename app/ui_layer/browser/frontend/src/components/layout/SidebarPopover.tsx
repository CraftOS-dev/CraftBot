import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

// Popup anchored to a sidebar control, portalled to <body> so it can extend
// past the sidebar's edge instead of being clipped by its scroll area. Opens
// below the anchor, flips above it when the viewport has no room below, and
// shifts left if it would run off the right edge.
export function SidebarPopover({
  anchor,
  className,
  role,
  children,
}: {
  anchor: DOMRect
  className: string
  role: 'menu' | 'tooltip'
  children: ReactNode
}) {
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
      className={className}
      role={role}
      // First pass renders hidden to measure; the layout effect places it
      // before paint.
      style={pos ?? { top: 0, left: 0, visibility: 'hidden' }}
      onMouseDown={e => e.stopPropagation()}
    >
      {children}
    </div>,
    document.body,
  )
}

