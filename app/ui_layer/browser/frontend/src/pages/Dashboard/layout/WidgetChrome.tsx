import type { ComponentType, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { GripVertical, X } from 'lucide-react'
import { IconButton } from '../../../components/ui'
import { WidgetErrorBoundary } from './WidgetErrorBoundary'
import styles from './WidgetChrome.module.css'

interface WidgetChromeProps {
  title: string
  icon: LucideIcon
  headerBadge?: ComponentType
  onRemove: () => void
  children: ReactNode
}

// Title bar doubles as the drag handle (`dashboardDragHandle`) for
// react-grid-layout's `draggableHandle`; the remove button carries a
// second plain class (`dashboardWidgetRemove`) that `draggableCancel`
// excludes from drag-start, so clicking it removes the widget instead of
// starting a drag. Both class names must stay unhashed (not CSS-module
// classes) since react-grid-layout matches them as real DOM selectors.
export function WidgetChrome({ title, icon: Icon, headerBadge: HeaderBadge, onRemove, children }: WidgetChromeProps) {
  return (
    <div className={styles.chrome}>
      <div className={`${styles.titleBar} dashboardDragHandle`}>
        <GripVertical size={12} className={styles.gripIcon} />
        <Icon size={14} className={styles.titleIcon} />
        <span className={styles.title}>{title}</span>
        {HeaderBadge && <HeaderBadge />}
        <IconButton
          icon={<X size={14} />}
          size="sm"
          tooltip={`Remove ${title}`}
          className={`${styles.removeBtn} dashboardWidgetRemove`}
          onClick={onRemove}
        />
      </div>
      <div className={styles.body}>
        <WidgetErrorBoundary title={title}>{children}</WidgetErrorBoundary>
      </div>
    </div>
  )
}
