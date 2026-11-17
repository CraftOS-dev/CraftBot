import { Chat } from '../../components/Chat'
import { useAppSelector } from '../../store/hooks'
import { FrameworkSessionPage } from '../AgentApp/FrameworkAppPage'
import styles from './ChatPage.module.css'

interface ChatPageProps {
  /** Session this page renders — "main" for the pinned main session,
   *  otherwise a chat session id from the /session/:id route. */
  sessionId: string
}

// Chat owns the conversation and its separate generated-output workspace.
export function ChatPage({ sessionId }: ChatPageProps) {
  const session = useAppSelector(state => state.sessions.sessions.find(item => item.id === sessionId))
  if (session?.type === 'agent_app' && (session.agentAppFrameworkPending || session.agentAppFrameworkKey)) {
    return <FrameworkSessionPage sessionId={sessionId} />
  }
  return (
    <div className={styles.chatPage}>
      <div className={styles.chatPanel}>
        <Chat sessionId={sessionId} />
      </div>
    </div>
  )
}
