import { useEffect } from 'react'
import { MainView } from './components/MainView'
import { AppController } from './AppController'
import { uiCapture } from './services/UICapture'

// Initialize the controller
const controller = new AppController()

function App() {
  useEffect(() => {
    // Start the controller on mount
    controller.initialize()

    // Register app state for UI capture (agent observation via HTTP)
    uiCapture.registerComponent('App', {
      initialized: true,
      componentName: 'App',
    })

    return () => {
      // Cleanup on unmount
      controller.cleanup()
      uiCapture.unregisterComponent('App')
    }
  }, [])

  return (
    <div className="app">
      <MainView controller={controller} />
    </div>
  )
}

export default App
