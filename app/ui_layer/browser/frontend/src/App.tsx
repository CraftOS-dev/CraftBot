import { Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/layout'
import { ChatPage } from './pages/Chat'
import { TasksPage } from './pages/Tasks'
import { DashboardPage } from './pages/Dashboard'
import { ScreenPage } from './pages/Screen'
import { WorkspacePage } from './pages/Workspace'
import { SettingsPage } from './pages/Settings'
import { useDynamicTabs } from './hooks/useDynamicTabs'
import { useTabWebSocketBridge } from './hooks/useTabWebSocketBridge'
import { buildDynamicRoutes } from './components/layout/DynamicRoutes'
import { DynamicTabFallback } from './components/tabs/DynamicTabLoader'

function App() {
  const { tabs } = useDynamicTabs()
  useTabWebSocketBridge()

  return (
    <Layout>
      <Suspense fallback={<DynamicTabFallback />}>
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/screen" element={<ScreenPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          {buildDynamicRoutes(tabs)}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  )
}

export default App
