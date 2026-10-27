import { forwardRef, useEffect, useId, useImperativeHandle, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { KeyboardEvent } from 'react'
import { referenceKey, type ReferenceCandidate } from './references'
import styles from './References.module.css'

export interface ReferenceAutocompleteHandle { handleKey: (event: KeyboardEvent<HTMLTextAreaElement>) => boolean }
interface Props {
  items: ReferenceCandidate[]
  open: boolean
  onSelect: (item: ReferenceCandidate) => void
  onClose: () => void
  onActive: (id: string | undefined, listId: string) => void
}

export const ReferenceAutocomplete = forwardRef<ReferenceAutocompleteHandle, Props>(function ReferenceAutocomplete(
  { items, open, onSelect, onClose, onActive }, ref,
) {
  const { t } = useTranslation('chat')
  const id = useId()
  const [selected, setSelected] = useState<string | null>(null)
  const index = Math.max(0, items.findIndex(item => referenceKey(item) === selected))
  useEffect(() => { onActive(open && items.length ? `${id}-${index}` : undefined, id) }, [open, items.length, id, index, onActive])
  useEffect(() => { if (open) document.getElementById(`${id}-${index}`)?.scrollIntoView({ block: 'nearest' }) }, [id, index, open])
  useImperativeHandle(ref, () => ({ handleKey(event) {
    if (!open || event.nativeEvent.isComposing) return false
    if (event.key === 'Escape') { onClose(); return true }
    // With nothing to choose the list is only a hint: Enter still sends.
    if (!items.length) return false
    if (event.key === 'Enter' && event.shiftKey) { onClose(); return false }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      setSelected(referenceKey(items[(index + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]))
      return true
    }
    if (event.key === 'Enter' || (event.key === 'Tab' && !event.shiftKey)) { onSelect(items[index]); return true }
    if (event.key === 'Tab') onClose()
    return false
  } }), [open, items, index, onSelect, onClose])
  if (!open) return null
  return <div className={styles.suggestions}>
    <ul id={id} role="listbox" aria-label={t('references.title')} className={styles.list}>
      {items.slice(0, 50).map((item, i) => <li id={`${id}-${i}`} key={referenceKey(item)} role="option"
        aria-selected={i === index} className={`${styles.option} ${i === index ? styles.active : ''}`}
        onMouseDown={e => e.preventDefault()} onMouseEnter={() => setSelected(referenceKey(item))} onClick={() => onSelect(item)}>
        <span>{item.label}</span><small>{t(`references.${item.kind}`)}</small>
      </li>)}
    </ul>
    {!items.length && <p role="status">{t('references.noMatches')}</p>}
  </div>
})
