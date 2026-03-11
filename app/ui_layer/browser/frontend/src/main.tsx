import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { WebSocketProvider } from './contexts/WebSocketContext'
import { WorkspaceProvider } from './contexts/WorkspaceContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { ToastProvider } from './contexts/ToastContext'
import { DynamicTabProvider } from './contexts/DynamicTabContext'
import './styles/global.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <ToastProvider>
          <WebSocketProvider>
            <WorkspaceProvider>
              <DynamicTabProvider>
                <App />
              </DynamicTabProvider>
            </WorkspaceProvider>
          </WebSocketProvider>
        </ToastProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
