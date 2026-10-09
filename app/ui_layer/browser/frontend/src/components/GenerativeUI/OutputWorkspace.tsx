import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowUpRight, Layers3, Maximize2, Minimize2, PanelRightClose, PanelRightOpen } from 'lucide-react'
import type { ChatMessage, GenerativeUIArtifact } from '../../types'
import { usePersistedState } from '../../hooks'
import { UI_STATE } from '../../store/uiState'
import { GenerativeUI } from './GenerativeUI'
import styles from './OutputWorkspace.module.css'

const OutputContext = createContext<((artifact: GenerativeUIArtifact) => void) | null>(null)

/** A small reference in the conversation; generated code only runs in the output pane. */
export function OutputReference({ artifact }: { artifact: GenerativeUIArtifact }) {
  const open = useContext(OutputContext)
  const { t } = useTranslation('chat')
  return <button type="button" className={styles.reference} onClick={() => open?.(artifact)} disabled={!open}>
    <span className={styles.referenceIcon}><Layers3 size={19} /></span>
    <span className={styles.referenceText}><strong>{artifact.title}</strong><span>{t('generativeUI.openOutput')}</span></span>
    <ArrowUpRight size={17} />
  </button>
}

export function OutputWorkspace({ sessionId, messages, children }: { sessionId: string; messages: ChatMessage[]; children: ReactNode }) {
  const { t } = useTranslation('chat')
  const [selection, setSelection] = usePersistedState(UI_STATE.chat.outputSelection(sessionId))
  const [fullscreen, setFullscreen] = useState(false)
  const closeButton = useRef<HTMLButtonElement>(null)
  const showButton = useRef<HTMLButtonElement>(null)
  const previousNewest = useRef<{ sessionId: string; key?: string }>({ sessionId })
  const outputs = useMemo(() => {
    const revisions = new Map<string, GenerativeUIArtifact>()
    for (const message of messages) {
      if (message.style === 'agent' && message.uiArtifact) {
        const artifact = message.uiArtifact
        revisions.set(`${artifact.id}:${artifact.revision}`, artifact)
      }
    }
    return Array.from(revisions.values())
  }, [messages])
  const newest = outputs[outputs.length - 1]
  const newestKey = newest ? `${newest.id}:${newest.revision}` : undefined
  const selected = outputs.find(artifact => `${artifact.id}:${artifact.revision}` === selection) ?? newest
  const isOpen = !!selected && selection !== 'closed'

  // Incoming outputs open automatically. Prepending older history or a language
  // synchronization must not reopen a pane that the user deliberately closed.
  useEffect(() => {
    const previous = previousNewest.current
    if (previous.sessionId === sessionId && newestKey && previous.key && previous.key !== newestKey) setSelection(newestKey)
    previousNewest.current = { sessionId, key: newestKey }
  }, [sessionId, newestKey, setSelection])
  useEffect(() => { setFullscreen(false) }, [sessionId])

  const open = (artifact: GenerativeUIArtifact) => {
    setSelection(`${artifact.id}:${artifact.revision}`)
    requestAnimationFrame(() => closeButton.current?.focus())
  }
  const close = () => { setSelection('closed'); setFullscreen(false); requestAnimationFrame(() => showButton.current?.focus()) }
  return <OutputContext.Provider value={open}>
    <div className={`${styles.workspace} ${isOpen ? styles.withOutput : ''} ${fullscreen ? styles.fullscreen : ''}`}>
      <div className={styles.conversation}>
        {outputs.length > 0 && <div className={styles.conversationBar}>
          <span>{t('generativeUI.conversation')}</span>
          <button type="button" ref={showButton} onClick={() => selected && open(selected)} aria-label={t('generativeUI.showOutputs')}><PanelRightOpen size={16} />{t('generativeUI.outputs')}</button>
        </div>}
        <div className={styles.chat}>{children}</div>
      </div>
      {isOpen && selected && <section className={styles.output} aria-label={t('generativeUI.outputPanel')} onKeyDown={event => {
        if (event.key === 'Escape' && fullscreen) { event.preventDefault(); setFullscreen(false) }
      }}>
        <header className={styles.header}>
          <div className={styles.title}><span>{t('generativeUI.output')}</span><h2>{selected.title}</h2></div>
          <div className={styles.headerActions}>
            {outputs.length > 1 && <select aria-label={t('generativeUI.selectOutput')} value={`${selected.id}:${selected.revision}`} onChange={event => setSelection(event.target.value)}>
              {outputs.map(artifact => <option key={`${artifact.id}:${artifact.revision}`} value={`${artifact.id}:${artifact.revision}`}>{outputs.every(item => item.id === selected.id) ? t('generativeUI.version', { revision: artifact.revision }) : `${artifact.title} · v${artifact.revision}`}</option>)}
            </select>}
            <button type="button" aria-label={t(fullscreen ? 'generativeUI.exitFullscreen' : 'generativeUI.fullscreen')} title={t(fullscreen ? 'generativeUI.exitFullscreen' : 'generativeUI.fullscreen')} onClick={() => setFullscreen(value => !value)}>{fullscreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}</button>
            <button type="button" ref={closeButton} aria-label={t('generativeUI.closeOutput')} title={t('generativeUI.closeOutput')} onClick={close}><PanelRightClose size={18} /></button>
          </div>
        </header>
        <GenerativeUI key={`${sessionId}:${selected.id}`} artifact={selected} sessionId={sessionId} />
      </section>}
    </div>
  </OutputContext.Provider>
}
