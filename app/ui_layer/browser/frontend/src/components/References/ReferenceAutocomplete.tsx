import { forwardRef, useEffect, useId, useImperativeHandle, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { KeyboardEvent } from 'react'
import { AppWindow, MessageSquare } from 'lucide-react'
import { AutocompleteMenu } from '../ui/AutocompleteMenu'
import { referenceKey, type ReferenceCandidate } from './references'

export interface ReferenceAutocompleteHandle { handleKey: (event: KeyboardEvent<HTMLTextAreaElement>) => boolean }
interface Props {
  items: ReferenceCandidate[]
  open: boolean
  onSelect: (item: ReferenceCandidate) => void
  onClose: () => void
  onActive: (id: string | undefined, listId: string) => void
}

/** Display order of the groups, like the "/" list's Commands then Skills. */
const GROUPS = [
  { kind: 'session', Icon: MessageSquare },
  { kind: 'agent_app', Icon: AppWindow },
] as const

/** The "@" suggestions: the same list as "/" commands (AutocompleteMenu). */
export const ReferenceAutocomplete = forwardRef<ReferenceAutocompleteHandle, Props>(function ReferenceAutocomplete(
  { items, open, onSelect, onClose, onActive }, ref,
) {
  const { t } = useTranslation('chat')
  const id = useId()
  const [selected, setSelected] = useState<string | null>(null)
  // Keyboard order must match the grouped display order.
  const ordered = useMemo(() => GROUPS.flatMap(({ kind }) => items.filter(item => item.kind === kind)), [items])
  const index = Math.max(0, ordered.findIndex(item => referenceKey(item) === selected))
  const shown = open && ordered.length > 0
  useEffect(() => { onActive(shown ? `${id}-${index}` : undefined, id) }, [shown, id, index, onActive])
  useImperativeHandle(ref, () => ({ handleKey(event) {
    if (!shown || event.nativeEvent.isComposing) return false
    if (event.key === 'Escape') { onClose(); return true }
    if (event.key === 'Enter' && event.shiftKey) { onClose(); return false }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      setSelected(referenceKey(ordered[(index + (event.key === 'ArrowDown' ? 1 : ordered.length - 1)) % ordered.length]))
      return true
    }
    if (event.key === 'Enter' || (event.key === 'Tab' && !event.shiftKey)) { onSelect(ordered[index]); return true }
    if (event.key === 'Tab') onClose()
    return false
  } }), [shown, ordered, index, onSelect, onClose])
  if (!shown) return null
  return <AutocompleteMenu
    id={id}
    label={t('references.title')}
    groups={GROUPS.map(({ kind, Icon }) => ({
      key: kind,
      icon: <Icon size={12} />,
      title: t(`references.${kind}`),
      items: ordered.filter(item => item.kind === kind).map(item => ({ key: referenceKey(item), label: item.label })),
    }))}
    selectedIndex={index}
    onSelect={i => onSelect(ordered[i])}
    onHover={i => setSelected(referenceKey(ordered[i]))}
  />
})
