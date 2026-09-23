import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import styles from './WidgetErrorBoundary.module.css'

// The boundary itself must be a class (getDerivedStateFromError), which can't
// use hooks — so the fallback UI lives in this small functional child, which
// re-renders with the active language like every other translated component.
function WidgetErrorFallback({ message, onRetry }: { message: string; onRetry: () => void }) {
  const { t } = useTranslation(['dashboard', 'common'])
  return (
    <div className={styles.fallback}>
      <AlertTriangle size={20} className={styles.icon} />
      <p className={styles.message}>{t('dashboard:errorBoundary.failed')}</p>
      <p className={styles.detail}>{message}</p>
      <button type="button" className={styles.retry} onClick={onRetry}>
        {t('common:actions.retry')}
      </button>
    </div>
  )
}

interface WidgetErrorBoundaryProps {
  /** Widget title, used to make the console error and retry label identifiable. */
  title: string
  children: ReactNode
}

interface WidgetErrorBoundaryState {
  error: Error | null
}

// Widgets pull their own data straight from the live WebSocket feed, so an
// unexpected shape in any payload throws during render. Without a boundary that
// unmounts the whole DashboardGrid and takes every other widget down with it.
// Scoping the boundary to a single widget keeps its neighbours — and the chrome's
// drag handle and remove button — alive, so a broken tile stays recoverable.
export class WidgetErrorBoundary extends Component<WidgetErrorBoundaryProps, WidgetErrorBoundaryState> {
  state: WidgetErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): WidgetErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[dashboard] widget "${this.props.title}" crashed:`, error, info.componentStack)
  }

  handleRetry = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return <WidgetErrorFallback message={error.message} onRetry={this.handleRetry} />
  }
}
