import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/layout'
import { ChatPage } from './pages/Chat'
import { TasksPage } from './pages/Tasks'
import { DashboardPage } from './pages/Dashboard'
import { ScreenPage } from './pages/Screen'
import { WorkspacePage } from './pages/Workspace'
import { SettingsPage } from './pages/Settings'
import { OnboardingPage } from './pages/Onboarding'
import { useWebSocket } from './contexts/WebSocketContext'

function App() {
  const { needsHardOnboarding } = useWebSocket()

  // Show onboarding page if hard onboarding is needed
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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

export default App
