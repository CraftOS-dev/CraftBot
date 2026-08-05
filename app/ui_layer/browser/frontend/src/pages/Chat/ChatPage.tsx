import { Chat } from '../../components/Chat'
import { MascotDisplay } from '@mascot'
import { useMascotVisibility } from '../../hooks'
import styles from './ChatPage.module.css'

interface ChatPageProps {
  /** Session this page renders — "main" for the pinned main session,
   *  otherwise a chat session id from the /session/:id route. */
  sessionId: string
}

// Per-session chat page: one linear timeline (messages + inline activity)
// with the input docked below. The old right-hand task panel is gone.
export function ChatPage({ sessionId }: ChatPageProps) {
  const [mascotVisible] = useMascotVisibility()

  return (
    <div className={styles.chatPage}>
      <div className={styles.chatPanel}>
        <Chat sessionId={sessionId} />
      </div>
      {mascotVisible && (
        <div className={styles.mascotDock}>
          <MascotDisplay />
        </div>
      )}
    </div>
  )
}
