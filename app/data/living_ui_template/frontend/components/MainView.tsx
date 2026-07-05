import { useAgentAware } from '../agent/hooks'
import type { AppController } from '../AppController'

interface MainViewProps {
  controller: AppController
}

/**
 * MainView - Primary view component
 * This is the main UI that users will see
 * Customize this component for your Living UI
 */
export function MainView({ controller }: MainViewProps) {
  // Make this component agent-aware
  useAgentAware('MainView', {
    currentSection: 'main',
  })

  return (
    <main className="main-view">
      <header className="view-header">
        <h1>{{PROJECT_NAME}}</h1>
        <p className="subtitle">{{PROJECT_DESCRIPTION}}</p>
      </header>

      <section className="view-content">
        {/* Your Living UI content goes here */}
        <div className="placeholder-content">
          <p>Welcome to your Living UI!</p>
          <p>Start building your custom interface here.</p>
        </div>
      </section>

      <style>{`
        .main-view {
          display: flex;
          flex-direction: column;
          min-height: 100vh;
          padding: var(--spacing-lg);
        }

        .view-header {
          margin-bottom: var(--spacing-lg);
        }

        .view-header h1 {
          font-size: 24px;
          font-weight: 600;
          margin-bottom: var(--spacing-xs);
        }

        .view-header .subtitle {
          color: var(--text-secondary);
          font-size: 14px;
        }

        .view-content {
          flex: 1;
        }

        .placeholder-content {
          background-color: var(--bg-secondary);
          border: 2px dashed var(--border-color);
          border-radius: var(--radius-lg);
          padding: var(--spacing-xl);
          text-align: center;
          color: var(--text-secondary);
        }

        .placeholder-content p {
          margin-bottom: var(--spacing-sm);
        }

        .placeholder-content p:last-child {
          margin-bottom: 0;
        }
      `}</style>
    </main>
  )
}
