import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Layout } from './components/layout'
import { ChatPage } from './pages/Chat'
import { DashboardPage } from './pages/Dashboard'
import { MemoryPage } from './pages/Memory'
import { ScreenPage } from './pages/Screen'
import { WorkspacePage } from './pages/Workspace'
import { SettingsPage } from './pages/Settings'
import { OnboardingPage } from './pages/Onboarding'
import { AgentAppPage } from './pages/AgentApp'
import { useWebSocket } from './contexts/WebSocketContext'
import { useAppSelector } from './store/hooks'
import { selectNeedsHardOnboarding } from './store/selectors/onboarding'
import { TourProvider } from './tour'
import { LoadingMascot } from '@mascot'
import { AgentAppImportToast } from './components/ui/AgentAppImportToast'

// Forces AgentAppPage to remount per-project so useState initializers
// (theme, custom colors) always start fresh - not carried over from a previous project.
function AgentAppPageRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  return <AgentAppPage key={projectId} />
}

// Per-session chat route. Deliberately NO key: /session/new ->
// /session/{id} must keep the same mounted ChatPage so the draft input's
// dock-to-bottom animation runs through the navigation. Chat resets its
// own per-session UI state internally on real session switches.
function SessionChatRoute() {
  const { id } = useParams<{ id: string }>()
  if (!id) return <Navigate to="/" replace />
  return <ChatPage sessionId={id} />
}

// How long the splash waits for the backend's initial state before saying
// something is wrong. Generous: a first run downloads the embedding model and
// boots MCP servers, skills, integrations and the scheduler before it sends
// init, and mistaking a slow boot for a dead one would be its own bug.
const BACKEND_INIT_TIMEOUT_MS = 90_000

function App() {
  const { t } = useTranslation(['nav', 'common'])
  const { initReceived } = useWebSocket()
  const needsHardOnboarding = useAppSelector(selectNeedsHardOnboarding)

  // The splash used to wait on initReceived forever. When the backend was not
  // coming — most often because an older CraftBot still held the port, so
  // these static files were served by an install whose backend had already
  // exited — "Waking up CraftBot..." was the entire user-visible failure
  // report, with the real reason sitting in a log file nobody was told about.
  const [initTimedOut, setInitTimedOut] = useState(false)
  useEffect(() => {
    if (initReceived) { setInitTimedOut(false); return }
    const timer = window.setTimeout(() => setInitTimedOut(true), BACKEND_INIT_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [initReceived])

  // Fade the main interface in once, right after the onboarding outro hands off
  // (the wizard sets this flag just before completing). One-shot via
  // sessionStorage so normal reloads don't fade.
  useEffect(() => {
    if (needsHardOnboarding) return
    let flagged = false
    try { flagged = sessionStorage.getItem('cb_onboarded_fade') === '1' } catch { /* ignore */ }
    if (!flagged) return
    try { sessionStorage.removeItem('cb_onboarded_fade') } catch { /* ignore */ }
    const root = document.getElementById('root')
    if (!root) return
    root.classList.add('cb-app-fade')
    const t = window.setTimeout(() => root.classList.remove('cb-app-fade'), 600)
    return () => window.clearTimeout(t)
  }, [needsHardOnboarding])

  // Block rendering until the backend sends the initial state.
  // Without this guard, needsHardOnboarding defaults to false and the chat
  // flashes briefly before the onboarding page appears on first install.
  if (!initReceived) {
    return (
      <div className="cb-splash" style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#191919',
        flexDirection: 'column',
        gap: '48px',
        userSelect: 'none',
      }}>
        <style>{`
          /* dvh with vh fallback (inline styles can't express the pair) */
          .cb-splash { height: 100vh; height: 100dvh; }
          /* Cycling loading dots: . -> .. -> ... -> repeat. inline-block with a
             reserved width so the phrase before it doesn't jitter as dots grow. */
          .cb-dots { display: inline-block; width: 1.4em; text-align: left; }
          .cb-dots::after { content: '.'; animation: cb-dots 1.4s steps(1, end) infinite; }
          @keyframes cb-dots {
            0%, 100% { content: '.'; }
            33%      { content: '..'; }
            66%      { content: '...'; }
          }
        `}</style>

        {/* Loading indicator: the mascot jumping in place (same character +
            jump beats as the Agent App build view). */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <LoadingMascot size={64} />
          {initTimedOut ? (
            <div style={{ maxWidth: '440px', textAlign: 'center' }}>
              <p style={{ margin: '0 0 8px', color: '#e0e0e0', fontSize: '15px' }}>
                {t('nav:app.backendUnreachable')}
              </p>
              <p style={{ margin: '0 0 16px', color: '#8a8a8a', fontSize: '13px', lineHeight: 1.6 }}>
                {t('nav:app.backendUnreachableHint')}
              </p>
              <button
                onClick={() => window.location.reload()}
                style={{
                  background: 'transparent', color: '#8a8a8a', fontSize: '13px',
                  border: '1px solid #3a3a3a', borderRadius: '6px',
                  padding: '6px 14px', cursor: 'pointer',
                }}
              >
                {t('nav:app.retry')}
              </button>
            </div>
          ) : (
            <p style={{ margin: 0, color: '#8a8a8a', fontSize: '14px' }}>
              {t('nav:app.wakingUp')}<span className="cb-dots" />
            </p>
          )}
        </div>
      </div>
    )
  }

  if (needsHardOnboarding) {
    return <OnboardingPage />
  }

  // TourProvider wraps the ready app (past hard onboarding), so the first-run
  // walkthrough can never collide with the onboarding wizard. It sits inside
  // the router, so the tour can navigate between pages.
  return (
    <TourProvider autoStartEnabled>
    {/* Root-level: an import outlives the modal that started it, so the
        progress/outcome toast has to be mounted somewhere that never
        unmounts. Renders nothing. */}
    <AgentAppImportToast />
    <Layout>
      <Routes>
        <Route path="/" element={<ChatPage key="main" sessionId="main" />} />
        <Route path="/session/:id" element={<SessionChatRoute />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/memory" element={<MemoryPage />} />
        <Route path="/screen" element={<ScreenPage />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/agent-app/:projectId" element={<AgentAppPageRoute />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
    </TourProvider>
  )
}

export default App
