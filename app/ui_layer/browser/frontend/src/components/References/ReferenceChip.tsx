import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AppWindow, MessageSquare, X } from 'lucide-react'
import type { ReferenceInput, ReferenceSnapshot } from '../../types'
import { ReferenceDialog } from './ReferenceDialog'
import { useAppSelector } from '../../store/hooks'
import styles from './References.module.css'

export function ReferenceChip({ reference, onRemove }: { reference: ReferenceInput & { label: string }; onRemove?: () => void }) {
  const { t } = useTranslation('chat')
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const snapshot = 'capturedAt' in reference && reference.capturedAt ? reference as ReferenceSnapshot : null
  const available = useAppSelector(state => reference.kind === 'session'
    ? state.sessions.sessions.some(s => s.id === reference.targetId)
    : reference.kind === 'agent_app' && state.agentApp.projects.some(a => a.id === reference.targetId))
  const Icon = reference.kind === 'session' ? MessageSquare : AppWindow
  return <>
    <span className={styles.chip}>
      <button type="button" className={styles.chipLabel} onClick={() => setOpen(true)} title={`${reference.label} · ${t('references.preview')}`}>
        <Icon size={13} aria-hidden="true" /><span className={styles.chipText}>{reference.label}</span>
      </button>
      {onRemove && <button type="button" className={styles.chipRemove} aria-label={t('references.remove', { name: reference.label })} onClick={onRemove}><X size={13} /></button>}
    </span>
    <ReferenceDialog open={open} onClose={() => setOpen(false)} title={reference.label}>
        {snapshot ? <><small>{t('references.captured', { time: snapshot.capturedAt })}</small><pre className={styles.excerpt}>{snapshot.excerpt}</pre>
          {snapshot.truncated && <p>{t('references.truncated')}</p>}</> : <p>{t('references.captureOnSend')}</p>}
        <p>{t('references.retention')}</p>
        {!available && <p role="status">{t('references.unavailable')}</p>}
        <button type="button" disabled={!available} onClick={() => { setOpen(false); navigate(reference.kind === 'session' ? `/session/${encodeURIComponent(reference.targetId)}` : `/agent-app/${encodeURIComponent(reference.targetId)}`) }}>{t('references.openSource')}</button>
    </ReferenceDialog>
  </>
}
