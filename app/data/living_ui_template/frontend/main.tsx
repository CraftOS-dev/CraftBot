import React from 'react'
import ReactDOM from 'react-dom/client'
import './styles/global.css'
import './styles/themes.css'

// Root error boundary: React unmounts the WHOLE tree when a render throws,
// which blanks the page. The boundary catches instead and shows the last
// working state captured by the dev engine (sessionStorage key kept in sync
// with devBuildMode's SNAPSHOT_KEY). The engine reloads the page once the
// next successful update arrives, so recovery is automatic.
class LastGoodBoundary extends React.Component<
  { children: React.ReactNode },
  { crashed: boolean }
> {
  state = { crashed: false }
  static getDerivedStateFromError() {
    return { crashed: true }
  }
  componentDidCatch() {
    ;(window as any).__CB_APP_CRASHED__ = true
  }
  render() {
    if (!this.state.crashed) return this.props.children
    let html = ''
    try {
      html = sessionStorage.getItem('craftbot-last-good-dom') || ''
    } catch {
      /* no snapshot available */
    }
    return <div dangerouslySetInnerHTML={{ __html: html }} />
  }
}

// App is imported DYNAMICALLY: while the agent is mid-build the app's module
// graph is regularly broken for a moment (half-written file), and a static
// import would take this whole entry module down with it — blank page. With
// a dynamic import this module always runs, so the dev engine can catch the
// failure and show the last working state instead.
const boot = () =>
  import('./App').then(({ default: App }) =>
    ReactDOM.createRoot(document.getElementById('root')!).render(
      <React.StrictMode>
        <LastGoodBoundary>
          <App />
        </LastGoodBoundary>
      </React.StrictMode>,
    ),
  )

// Dev server only (dead code in production builds): the Staged Reveal Engine
// choreographs new UI into view while CraftBot builds this app, plus API
// fallbacks for the not-yet-running backend, HMR status for the host, and a
// last-good-state fallback when the app fails to boot mid-build. React boots
// AFTER the engine so its staging CSS beats the first paint; if the engine
// fails to load, boot proceeds normally.
if (import.meta.env.DEV) {
  import('./agent/devBuildMode').then(
    engine => engine.bootApp(boot),
    () => void boot(),
  )
} else {
  void boot()
}
