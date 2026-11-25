import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Clock, ShieldAlert } from 'lucide-react'
import { Button } from '../ui'
import { useToast } from '../../contexts/ToastContext'
import { formatList } from '../../i18n/format'
import { useAppSelector } from '../../store/hooks'
import { getSocketClient } from '../../store/socket/socketInstance'
import type { ApprovalDecision, ApprovalRequest, SecurityEffect } from '../../store/slices/securitySlice'
import styles from './ApprovalCard.module.css'

const MAIN_SESSION_ID = 'main'
/** Inputs longer than this many lines start collapsed. */
const INPUT_PREVIEW_LINES = 8
const EFFECTS: SecurityEffect[] = ['execute', 'write_files', 'send_external', 'change_agent', 'use_credentials']

const isEffect = (value: string): value is SecurityEffect => (EFFECTS as string[]).includes(value)

// "4:05"
function formatCountdown(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** The current time, updated every second while mounted. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

/**
 * Approval cards above the chat composer (Settings → Security, Auto mode off).
 *
 * Shows every pending request of `sessionId`. The main chat also shows
 * requests whose session is not a chat the sidebar knows, so none can wait
 * unseen; requests of other chats get a one-line pointer instead. A card
 * leaves when the backend reports the request resolved (answered here, in
 * another window or the terminal, timed out or cancelled).
 */
export function ApprovalCards({ sessionId }: { sessionId: string }) {
  const { t } = useTranslation(['chat', 'nav'])
  const navigate = useNavigate()
  const approvals = useAppSelector(state => state.security.approvals)
  const sessions = useAppSelector(state => state.sessions.sessions)

  const { shown, elsewhere } = useMemo(() => {
    const known = new Set(sessions.map(s => s.id))
    known.add(MAIN_SESSION_ID)
    const shown: ApprovalRequest[] = []
    const elsewhere = new Map<string, number>()
    const ordered = [...approvals].sort((a, b) => a.created_at - b.created_at)
    for (const request of ordered) {
      if (request.session_id === sessionId) shown.push(request)
      else if (!known.has(request.session_id)) {
        if (sessionId === MAIN_SESSION_ID) shown.push(request)
      } else elsewhere.set(request.session_id, (elsewhere.get(request.session_id) ?? 0) + 1)
    }
    return { shown, elsewhere }
  }, [approvals, sessions, sessionId])

  if (shown.length === 0 && elsewhere.size === 0) return null

  const sessionTitle = (id: string) => {
    if (id === MAIN_SESSION_ID) return t('nav:items.main')
    return sessions.find(s => s.id === id)?.title || t('chat:approval.unknownSession')
  }

  return (
    <div className={styles.stack}>
      {[...elsewhere].map(([id, count]) => (
        <div key={id} className={styles.elsewhere} role="status">
          <ShieldAlert size={14} className={styles.icon} />
          <span className={styles.elsewhereText}>
            {t('chat:approval.waitingIn', { count, session: sessionTitle(id) })}
          </span>
          <button
            type="button"
            className={styles.elsewhereOpen}
            onClick={() => navigate(id === MAIN_SESSION_ID ? '/' : `/session/${encodeURIComponent(id)}`)}
          >
            {t('chat:approval.open')}
            <ArrowRight size={12} />
          </button>
        </div>
      ))}
      {shown.map(request => (
        <ApprovalCard
          key={request.id}
          request={request}
          sessionLabel={request.session_id === sessionId ? null : sessionTitle(request.session_id)}
        />
      ))}
    </div>
  )
}

interface ApprovalCardProps {
  request: ApprovalRequest
  /** Set when the request belongs to another session than the open chat. */
  sessionLabel: string | null
}

function ApprovalCard({ request, sessionLabel }: ApprovalCardProps) {
  const { t } = useTranslation(['chat', 'common'])
  const { showToast } = useToast()
  // The answer sent; buttons stay disabled until the card is resolved away.
  const [answered, setAnswered] = useState<ApprovalDecision | null>(null)
  const [expanded, setExpanded] = useState(false)
  const now = useNow()

  const remaining = Math.max(0, Math.ceil(request.expires_at - now / 1000))
  const expired = remaining === 0
  const action = request.action_display_name || request.action_name

  const inputsText = useMemo(() => JSON.stringify(request.inputs ?? {}, null, 2), [request.inputs])
  const lines = inputsText.split('\n')
  const isLong = lines.length > INPUT_PREVIEW_LINES
  const hasInputs = Object.keys(request.inputs ?? {}).length > 0

  let reason: string | null
  if (request.reason === 'risky_command') {
    reason = t('chat:approval.risky', { detail: request.reason_detail })
  } else if (request.reason === 'untrusted_content') {
    reason = request.reason_detail
      ? t('chat:approval.untrusted', { detail: request.reason_detail })
      : t('chat:approval.untrustedNoDetail')
  } else {
    const effects = request.effects.filter(isEffect).map(effect => t(`chat:approval.effects.${effect}`))
    reason = effects.length > 0 ? t('chat:approval.highRisk', { effects: formatList(effects) }) : null
  }

  const answer = (decision: ApprovalDecision) => {
    if (answered || expired) return
    setAnswered(decision)
    // Not queued for a reconnect: by then the request may be gone or have a
    // new card, and an old answer must not land on it.
    const sent = getSocketClient().sendNow('security_approval_response', { id: request.id, decision })
    if (!sent) {
      setAnswered(null)
      showToast('error', t('chat:approval.notConnected'))
    }
  }

  const disabled = answered !== null || expired

  return (
    <div
      className={styles.box}
      role="region"
      aria-label={t('chat:approval.aria')}
      onClickCapture={event => {
        // The next card can move under the pointer between clicks; only the
        // first click of a sequence acts (keyboard clicks have detail 0).
        if (event.detail > 1) event.stopPropagation()
      }}
    >
      <div className={styles.header}>
        <ShieldAlert size={14} className={styles.icon} />
        <span className={styles.title}>{t('chat:approval.title', { action })}</span>
        {sessionLabel && (
          <span className={styles.sessionBadge} title={request.session_id}>
            {t('chat:approval.inSession', { session: sessionLabel })}
          </span>
        )}
        <span className={`${styles.countdown} ${remaining <= 30 ? styles.countdownUrgent : ''}`} aria-live="off">
          <Clock size={12} />
          {expired
            ? t('chat:approval.expired')
            : t('chat:approval.expiresIn', { time: formatCountdown(remaining) })}
        </span>
      </div>

      {reason && <p className={styles.reason}>{reason}</p>}

      {hasInputs && (
        <div className={styles.inputs}>
          <span className={styles.inputsLabel}>{t('chat:approval.inputs')}</span>
          <pre className={`${styles.inputsBlock} ${expanded ? styles.inputsExpanded : ''}`}>
            {isLong && !expanded ? `${lines.slice(0, INPUT_PREVIEW_LINES).join('\n')}\n…` : inputsText}
          </pre>
          {isLong && (
            <button type="button" className={styles.moreToggle} onClick={() => setExpanded(v => !v)}>
              {expanded
                ? t('chat:approval.showLess')
                : t('chat:approval.showAll', { count: lines.length })}
            </button>
          )}
        </div>
      )}

      <div className={styles.actions}>
        <Button variant="primary" size="sm" onClick={() => answer('allow_once')} disabled={disabled}
          loading={answered === 'allow_once'}>
          {t('chat:approval.allowOnce')}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => answer('allow_session')} disabled={disabled}
          loading={answered === 'allow_session'} title={request.grant_scope === 'command' ? t('chat:approval.allowSessionHintCommand') : t('chat:approval.allowSessionHint', { action })}>
          {t('chat:approval.allowSession')}
        </Button>
        <Button variant="secondary" size="sm" className={styles.deny} onClick={() => answer('deny')} disabled={disabled}
          loading={answered === 'deny'}>
          {t('chat:approval.deny')}
        </Button>
      </div>
    </div>
  )
}
