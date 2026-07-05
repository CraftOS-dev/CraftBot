import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { uiCapture } from './services/UICapture'
import './styles/global.css'

// Get backend URL — detected from manifest at runtime, falls back to env/default
const backendBase = (window as any).__CRAFTBOT_BACKEND_URL__ || `http://localhost:${import.meta.env.VITE_BACKEND_PORT || '3101'}`
const backendUrl = `${backendBase}/api`

// Initialize UI capture for agent observation (event-driven, no polling)
// This replaces WebSocket-based AgentBridge with HTTP
uiCapture.initialize(backendUrl)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
