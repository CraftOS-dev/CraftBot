import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Provider as ReduxProvider } from 'react-redux'
import App from './App'
import { WebSocketProvider } from './contexts/WebSocketContext'
import { WorkspaceProvider } from './contexts/WorkspaceContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { ToastProvider } from './contexts/ToastContext'
import { FullscreenProvider } from './contexts/FullscreenContext'
import { store } from './store'
import './i18n/config'
import './styles/global.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ReduxProvider store={store}>
      <BrowserRouter>
        <ThemeProvider>
          <ToastProvider>
            <WebSocketProvider>
              <WorkspaceProvider>
                <FullscreenProvider>
                  <App />
                </FullscreenProvider>
              </WorkspaceProvider>
            </WebSocketProvider>
          </ToastProvider>
        </ThemeProvider>
      </BrowserRouter>
    </ReduxProvider>
  </React.StrictMode>,
)
