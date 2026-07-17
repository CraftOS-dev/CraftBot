import { Toaster } from '@/components/ui/sonner'
import { MainView } from './components/MainView'

function App() {
  return (
    <div className="app">
      <MainView />
      {/* Global toast outlet (sonner) — never mount a second one. */}
      <Toaster />
    </div>
  )
}

export default App
