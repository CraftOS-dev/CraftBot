import { createContext, useContext } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowUpRight, Layers3 } from 'lucide-react'
import type { GenerativeUIArtifact, ClosedGenerativeUIArtifact } from '../../types'
import styles from './ChatWorkspace.module.css'

export const OutputContext = createContext<((artifact: GenerativeUIArtifact) => void) | null>(null)

/** A small reference in the conversation; generated code only runs in the
 *  output pane. A closed output stays listed, without anything to open. */
export function OutputReference({ artifact }: { artifact: GenerativeUIArtifact | ClosedGenerativeUIArtifact }) {
  const open = useContext(OutputContext)
  const { t } = useTranslation('chat')
  if (artifact.closed) {
    return <div className={`${styles.reference} ${styles.referenceClosed}`}>
      <span className={styles.referenceIcon}><Layers3 size={19} /></span>
      <span className={styles.referenceText}><strong>{artifact.title}</strong><span>{t('generativeUI.closed')}</span></span>
    </div>
  }
  return <button type="button" className={styles.reference} onClick={() => open?.(artifact)} disabled={!open}>
    <span className={styles.referenceIcon}><Layers3 size={19} /></span>
    <span className={styles.referenceText}><strong>{artifact.title}</strong><span>{t('generativeUI.openOutput')}</span></span>
    <ArrowUpRight size={17} />
  </button>
}
