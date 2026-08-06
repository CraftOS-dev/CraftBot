import { useEffect, useRef, useState } from 'react'
import { Responsive } from 'react-grid-layout'
import type { Layout, Layouts } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import './DashboardGrid.overrides.css'
import { WIDGET_REGISTRY } from '../widgets/registry'
import { WidgetChrome } from './WidgetChrome'
import {
  BREAKPOINTS,
  COLS,
  CONTAINER_PADDING,
  MARGIN,
  breakpointFromWidth,
  columnWidth,
} from './constants'
import type { BreakpointLayouts, NamedLayout } from './types'
import styles from './DashboardGrid.module.css'

interface DashboardGridProps {
  activeLayout: NamedLayout
  onLayoutsChange: (layouts: BreakpointLayouts) => void
  onRemoveWidget: (widgetId: string) => void
}

export function DashboardGrid({ activeLayout, onLayoutsChange, onRemoveWidget }: DashboardGridProps) {
  // Measured rather than taken from RGL's WidthProvider, for two reasons: the
  // row height has to be derived from this same number to keep cells square,
  // and WidthProvider only re-measures on *window* resize — so anything that
  // changes the dashboard's width without resizing the window (collapsing the
  // sidebar, a scrollbar appearing) left it stale.
  const hostRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    const observer = new ResizeObserver(entries => {
      const next = entries[0]?.contentRect.width ?? 0
      setWidth(prev => (Math.abs(prev - next) < 0.5 ? prev : next))
    })
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  // Guard against stale/corrupted storage referencing a widget id that no
  // longer exists in the registry.
  const widgetIds = activeLayout.widgetIds.filter(id => WIDGET_REGISTRY[id])

  const cols = COLS[breakpointFromWidth(width)]
  // Square cells: one row is exactly as tall as one column is wide, which is
  // what makes a 2x2 or 5x5 widget an actual square. RGL takes a fractional
  // rowHeight fine, and rounding here would compound across five rows.
  const rowHeight = columnWidth(width, cols)

  // One host element for every state — empty layout included. The observer is
  // attached once, so the node it holds must never be swapped out from under
  // it: an early `return` for the empty state would leave it watching a
  // detached div once the first widget was added.
  return (
    <div ref={hostRef} className={styles.gridHost}>
      {widgetIds.length === 0 && (
        <div className={styles.emptyState}>
          No widgets on this layout yet — click "Add Widget" to get started.
        </div>
      )}

      {/* Laying the grid out against width 0 and then correcting would show a
          visible jump on every mount; wait for the first measurement. */}
      {widgetIds.length > 0 && width > 0 && (
        <Responsive
          width={width}
          layouts={activeLayout.layouts as unknown as Layouts}
          breakpoints={BREAKPOINTS}
          cols={COLS}
          rowHeight={rowHeight}
          margin={MARGIN}
          containerPadding={CONTAINER_PADDING}
          compactType="vertical"
          isDraggable
          isResizable
          draggableHandle=".dashboardDragHandle"
          draggableCancel=".dashboardWidgetRemove"
          onLayoutChange={(_current: Layout[], all: Layouts) => onLayoutsChange(all as unknown as BreakpointLayouts)}
        >
          {widgetIds.map(id => {
            const def = WIDGET_REGISTRY[id]
            const Comp = def.component
            return (
              <div key={id}>
                <WidgetChrome title={def.title} icon={def.icon} headerBadge={def.headerBadge} onRemove={() => onRemoveWidget(id)}>
                  <Comp />
                </WidgetChrome>
              </div>
            )
          })}
        </Responsive>
      )}
    </div>
  )
}
