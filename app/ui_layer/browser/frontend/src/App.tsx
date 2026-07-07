import React from 'react'
import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Layout } from './components/layout'
import { ChatPage } from './pages/Chat'
import { TasksPage } from './pages/Tasks'
import { DashboardPage } from './pages/Dashboard'
import { ScreenPage } from './pages/Screen'
import { WorkspacePage } from './pages/Workspace'
import { SettingsPage } from './pages/Settings'
import { OnboardingPage } from './pages/Onboarding'
import { LivingUIPage } from './pages/LivingUI'
import { MarketplacePage, ProductDetailPage } from './pages/Marketplace'
import { useWebSocket } from './contexts/WebSocketContext'

// Forces LivingUIPage to remount per-project so useState initializers
// (theme, custom colors) always start fresh — not carried over from a previous project.
function LivingUIPageRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  return <LivingUIPage key={projectId} />
}

function App() {
  const { initReceived, needsHardOnboarding } = useWebSocket()

  // Block rendering until the backend sends the initial state.
  // Without this guard, needsHardOnboarding defaults to false and the chat
  // flashes briefly before the onboarding page appears on first install.
  if (!initReceived) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        background: '#191919',
        flexDirection: 'column',
        gap: '48px',
        userSelect: 'none',
      }}>
        <style>{`
          @keyframes cb-dot {
            0%, 80%, 100% { transform: scale(0.45); opacity: 0.25; }
            40%            { transform: scale(1);    opacity: 1;    }
          }
        `}</style>

        <img
          src="/craftbot_logo_text_no_border_dark.png"
          alt="CraftBot"
          style={{ width: '210px', pointerEvents: 'none' }}
        />

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#f04a00', animation: 'cb-dot 1.4s ease-in-out infinite 0s' }} />
          <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#f04a00', animation: 'cb-dot 1.4s ease-in-out infinite 0.18s' }} />
          <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#f04a00', animation: 'cb-dot 1.4s ease-in-out infinite 0.36s' }} />
        </div>
      </div>
    )
  }

  if (needsHardOnboarding) {
    return <OnboardingPage />
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/screen" element={<ScreenPage />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/marketplace" element={<MarketplacePage />} />
        <Route path="/marketplace/:type/:slug" element={<ProductDetailPage />} />
        <Route path="/living-ui/:projectId" element={<LivingUIPageRoute />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

export default App
