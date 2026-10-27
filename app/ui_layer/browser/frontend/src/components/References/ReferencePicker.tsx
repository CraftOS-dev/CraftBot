import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AppWindow, Check, MessageSquare, Search } from 'lucide-react'
import { referenceKey, searchReferences, type ReferenceCandidate } from './references'
import type { ReferenceInput } from '../../types'
import styles from './References.module.css'

interface Props {
  open: boolean
  items: ReferenceCandidate[]
  selected: ReferenceInput[]
  onSelect: (item: ReferenceCandidate) => boolean
  onRemove: (item: ReferenceInput) => void
  onClose: () => void
}

/** Nested + menu context picker; selections stay visible in the chat draft. */
export function ReferencePicker({ open, items, selected, onSelect, onRemove, onClose }: Props) {
  const { t } = useTranslation(['chat', 'common'])
  const [query, setQuery] = useState('')
  const [placement, setPlacement] = useState({ left: 0, top: 0, maxHeight: 400 })
  const root = useRef<HTMLDivElement>(null)
  const search = useRef<HTMLInputElement>(null)
  const close = useRef(onClose)
  close.current = onClose
  const results = useMemo(() => searchReferences(items, query).sort((a, b) => Number(a.kind === 'agent_app') - Number(b.kind === 'agent_app')), [items, query])
  const selectedKeys = new Set(selected.map(referenceKey))

  useLayoutEffect(() => {
    if (!open) return
    const position = () => {
      const anchor = root.current?.parentElement?.getBoundingClientRect()
      if (!anchor) return
      const width = Math.min(260, window.innerWidth - 16)
      const height = Math.min(root.current?.scrollHeight || 400, 400, window.innerHeight - 16)
      const right = anchor.right + 6
      const left = right + width <= window.innerWidth - 8 ? right : Math.max(8, anchor.left - width - 6)
      setPlacement({ left, top: Math.max(8, Math.min(anchor.top, window.innerHeight - height - 8)), maxHeight: Math.min(400, window.innerHeight - 16) })
    }
    position()
    window.addEventListener('resize', position)
    return () => window.removeEventListener('resize', position)
  }, [open])

  useEffect(() => {
    if (!open) return
    setQuery('')
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.parentElement?.contains(event.target)) close.current()
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])

  const toggle = (item: ReferenceCandidate) => {
    if (selectedKeys.has(referenceKey(item))) onRemove(item)
    else if (!onSelect(item)) return
    onClose()
  }
  if (!open) return null

  return <div ref={root} role="dialog" aria-label={t('chat:references.pickerTitle')}
    className={styles.pickerPopover} style={placement}
    onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose() }
    }}>
    <div className={styles.searchField}>
      <Search size={15} aria-hidden="true" />
      <input data-context-search ref={search} aria-label={t('chat:references.search')} placeholder={t('chat:references.search')} value={query}
        onChange={event => setQuery(event.target.value)}
        onKeyDown={event => {
          if (event.nativeEvent.isComposing) return
          if (event.key === 'ArrowDown') { event.preventDefault(); root.current?.querySelector<HTMLButtonElement>('[data-reference-row]:not(:disabled)')?.focus() }
          if (event.key === 'Enter' && results[0]) { event.preventDefault(); toggle(results[0]) }
        }} />
    </div>
    <div className={styles.pickerResults}>
      {results.map((item, index) => {
        const isSelected = selectedKeys.has(referenceKey(item))
        const Icon = item.kind === 'session' ? MessageSquare : AppWindow
        return <div key={referenceKey(item)}>
          {(index === 0 || results[index - 1].kind !== item.kind) && <div className={styles.groupLabel}>{t(`chat:references.${item.kind}`)}</div>}
          <button type="button" data-reference-row title={item.label} className={styles.sourceRow}
          aria-pressed={isSelected} disabled={!isSelected && selected.length >= 8} onClick={() => toggle(item)}
          onKeyDown={event => {
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
            event.preventDefault()
            const rows = Array.from(root.current?.querySelectorAll<HTMLButtonElement>('[data-reference-row]:not(:disabled)') || [])
            const index = rows.indexOf(event.currentTarget)
            rows[(index + (event.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length]?.focus()
          }}>
          <span className={styles.sourceIcon}><Icon size={14} aria-hidden="true" /></span>
          <span className={styles.sourceText}>
            <span className={styles.sourceTitle}>{item.label}</span>
          </span>
          <span className={styles.selectionMark}>{isSelected && <Check size={12} aria-hidden="true" />}</span>
        </button></div>
      })}
      {!results.length && <div className={styles.empty} role="status"><Search size={22} aria-hidden="true" /><span>{t('chat:references.noMatches')}</span><small>{t('chat:references.emptyHint')}</small></div>}
    </div>
  </div>
}
