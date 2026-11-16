import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Link, Loader2 } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { receiveFrameworkAttachment } from '../../store/slices/agentAppSlice'
import { frameworkRequest, type FrameworkAttachment } from './frameworkApi'
import { frameUrl } from './frameHost'
import { frameworkRoute } from './frameworkIdentity'
import styles from '../../components/ui/CreateAgentAppModal.module.css'

interface ConnectionAttempt {
  id?: string
  status: 'pending' | 'connected' | 'error' | 'cancelled'
  approvalUrl?: string
  /** The app lets this page show its approval page, so no tab opens. */
  embeddable?: boolean
  /** Approved and signed in; CraftBot is adding the app. */
  finishing?: boolean
  attachment?: FrameworkAttachment
  error?: string
}

/** Sign in upstream, then open the same workspace used by installed apps. */
export function ConnectAgentApp({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const dispatch = useAppDispatch()
  const { requestAgentAppList } = useWebSocket()
  const connected = useAppSelector(s => s.connection.connected)
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState<ConnectionAttempt>()
  // The approval page's only full page change is the hand-back after
  // Approve: a bare page of the sign-in's own, covered the moment it loads
  // and until the app opens.
  const [handedBack, setHandedBack] = useState(false)
  const [frameKey, setFrameKey] = useState(0)
  const frameLoads = useRef(0)
  const active = useRef(true)
  const pending = useRef(false)
  const attemptId = useRef<string>()
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
      if (attemptId.current) void frameworkRequest({ operation: 'connect_cancel', id: attemptId.current }).catch(() => {})
    }
  }, [])
  const receive = useCallback((value: ConnectionAttempt) => {
    if (!active.current) {
      if (value.id && value.status === 'pending') void frameworkRequest({ operation: 'connect_cancel', id: value.id }).catch(() => {})
      return
    }
    attemptId.current = value.status === 'pending' ? value.id : undefined
    setAttempt(value)
    if (value.status === 'connected' && value.attachment) {
      dispatch(receiveFrameworkAttachment(value.attachment))
      requestAgentAppList()
      navigate(frameworkRoute(value.attachment.path, value.attachment.appId))
      onClose()
    } else if (value.status !== 'pending') {
      setError(value.error || 'Connection cancelled. You can try again.')
      setBusy(false)
      pending.current = false
    }
  }, [dispatch, navigate, onClose, requestAgentAppList])
  useEffect(() => {
    if (!attempt?.id || attempt.status !== 'pending') return
    // Faster while the approval page is shown here, so an approval is
    // confirmed soon after its hand-back is covered.
    const timer = window.setTimeout(() => {
      void frameworkRequest<ConnectionAttempt>({ operation: 'connect_status', id: attempt.id })
        .then(receive).catch(e => { if (active.current) { setError(String(e)); setBusy(false); pending.current = false } })
    }, attempt.embeddable ? 400 : 1000)
    return () => window.clearTimeout(timer)
  }, [attempt, receive])
  useEffect(() => {
    if (!handedBack || attempt?.finishing) return
    // Not confirmed: the person followed the page's "Back to the app" link
    // instead of approving. Show the approval page again.
    const timer = window.setTimeout(() => {
      frameLoads.current = 0
      setHandedBack(false)
      setFrameKey(key => key + 1)
    }, 3000)
    return () => window.clearTimeout(timer)
  }, [handedBack, attempt?.finishing])
  const connect = async () => {
    if (pending.current || !connected) return
    pending.current = true
    frameLoads.current = 0
    setHandedBack(false)
    setBusy(true); setError(''); setAttempt(undefined)
    try { receive(await frameworkRequest<ConnectionAttempt>({ operation: 'connect', url: url.trim(), embedder: window.location.origin })) }
    catch (e) { if (active.current) { setError(e instanceof Error ? e.message : String(e)); setBusy(false); pending.current = false } }
  }
  return <form style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }} onSubmit={e => { e.preventDefault(); void connect() }}>
    {attempt?.approvalUrl && attempt.embeddable
      // The app's own approval page takes the whole body, in place of a new
      // tab; it names the app itself. It may not navigate CraftBot.
      ? <div className={styles.approvalFrame}>
        <iframe key={`${attempt.approvalUrl} ${frameKey}`} src={frameUrl(attempt.approvalUrl)} title="Approve access"
          sandbox="allow-scripts allow-same-origin allow-forms"
          onLoad={() => { if (frameLoads.current++ > 0) setHandedBack(true) }} />
        {(handedBack || attempt.finishing) && <div className={styles.approvalCover} role="status" aria-label="Finishing">
          <Loader2 size={20} className={styles.spinner} />
        </div>}
      </div>
      : <div className={styles.modalBody}><div className={styles.centeredForm}><div className={styles.formGroup}>
        <label className={styles.label} htmlFor="agent-app-connect-url">Running app URL</label>
        <input id="agent-app-connect-url" type="url" className={styles.input} placeholder="https://app.example.com"
          value={url} onChange={e => setUrl(e.target.value)} disabled={busy} required />
        <span className={styles.hint}>Connect to an Agent App that is already running. Approve access in the app to use it with CraftBot.</span>
        {attempt?.approvalUrl && <>
          <a href={attempt.approvalUrl} target="_blank" rel="noopener noreferrer">Approve access</a>
          <span className={styles.hint} role="status">Waiting for approval. This window will update when you finish.</span>
        </>}
        {error && <span role="alert" className={styles.hint} style={{ color: 'var(--color-error)' }}>{error}</span>}
      </div></div></div>}
    <div className={styles.modalFooter}>
      <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
      <Button type="submit" icon={<Link size={16} />} loading={busy} disabled={!url.trim() || busy || !connected}>Connect</Button>
    </div>
  </form>
}
