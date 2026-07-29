import { Responsive, WidthProvider } from 'react-grid-layout'
import type { Layout, Layouts } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import './DashboardGrid.overrides.css'
import { WIDGET_REGISTRY } from '../widgets/registry'
import { WidgetChrome } from './WidgetChrome'
import { BREAKPOINTS, COLS, CONTAINER_PADDING, MARGIN, ROW_HEIGHT } from './constants'
import type { BreakpointLayouts, NamedLayout } from './types'
import styles from './DashboardGrid.module.css'

const ResponsiveGridLayout = WidthProvider(Responsive)

interface DashboardGridProps {
  activeLayout: NamedLayout
  onLayoutsChange: (layouts: BreakpointLayouts) => void
  onRemoveWidget: (widgetId: string) => void
}

export function DashboardGrid({ activeLayout, onLayoutsChange, onRemoveWidget }: DashboardGridProps) {
  // Guard against stale/corrupted storage referencing a widget id that no
  // longer exists in the registry.
  const widgetIds = activeLayout.widgetIds.filter(id => WIDGET_REGISTRY[id])

  if (widgetIds.length === 0) {
    return (
      <div className={styles.emptyState}>
        No widgets on this layout yet — click "Add Widget" to get started.
      </div>
    )
  }

  return (
    <ResponsiveGridLayout
      layouts={activeLayout.layouts as unknown as Layouts}
      breakpoints={BREAKPOINTS}
      cols={COLS}
      rowHeight={ROW_HEIGHT}
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
    </ResponsiveGridLayout>
  )
}
