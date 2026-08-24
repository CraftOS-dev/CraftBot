import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Layout } from './components/layout'
import { ChatPage } from './pages/Chat'
import { DashboardPage } from './pages/Dashboard'
import { MemoryPage } from './pages/Memory'
import { ScreenPage } from './pages/Screen'
import { WorkspacePage } from './pages/Workspace'
import { SettingsPage } from './pages/Settings'
import { OnboardingPage } from './pages/Onboarding'
import { LivingUIPage } from './pages/LivingUI'
import { useWebSocket } from './contexts/WebSocketContext'
import { TourProvider } from './tour'
import { LoadingMascot } from '@mascot'

// Forces LivingUIPage to remount per-project so useState initializers
// (theme, custom colors) always start fresh — not carried over from a previous project.
function LivingUIPageRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  return <LivingUIPage key={projectId} />
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

function App() {
  const { initReceived, needsHardOnboarding } = useWebSocket()

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
            jump beats as the Living UI build view). */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <LoadingMascot size={64} />
          <p style={{ margin: 0, color: '#8a8a8a', fontSize: '14px' }}>
            Waking up CraftBot<span className="cb-dots" />
          </p>
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
    <Layout>
      <Routes>
        <Route path="/" element={<ChatPage key="main" sessionId="main" />} />
        <Route path="/session/:id" element={<SessionChatRoute />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/memory" element={<MemoryPage />} />
        <Route path="/screen" element={<ScreenPage />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/living-ui/:projectId" element={<LivingUIPageRoute />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
    </TourProvider>
  )
}

export default App
