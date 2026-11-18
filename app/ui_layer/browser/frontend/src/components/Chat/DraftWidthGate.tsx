import { useLayoutEffect, useRef, type CSSProperties } from 'react'
import { ChatMessageItem } from '../../pages/Chat/ChatMessage'
import type { ChatMessage } from '../../types'

// A reply bubble being written appears only once its width is final, so it
// never widens while its first line is written. Its width is final when its
// text already fills the widest a bubble gets (from there it only grows
// downward), or when the message is complete (the caller shows it then).
//
// This lays each waiting draft out invisibly in the timeline column, beside
// a bubble filled to that widest width, and reports each draft that reached
// it. Rendered inside the timeline column so both get the rows' width.

const FULL_WIDTH_TEXT = 'm '.repeat(400)
const noop = () => {}

const hidden: CSSProperties = {
  position: 'absolute',
  top: 0,
  left: 0,
  width: '100%',
  height: 0,
  overflow: 'hidden',
  visibility: 'hidden',
  pointerEvents: 'none',
}

export function DraftWidthGate({
  drafts,
  onSettled,
}: {
  /** Drafts not shown yet (each carries its id as clientId). */
  drafts: ChatMessage[]
  onSettled: (id: string) => void
}) {
  const fullRef = useRef<HTMLDivElement>(null)
  const slots = useRef(new Map<string, HTMLDivElement>())

  useLayoutEffect(() => {
    const full = fullRef.current?.firstElementChild?.getBoundingClientRect().width ?? 0
    if (full <= 0) return
    for (const draft of drafts) {
      const id = draft.clientId
      const bubble = id ? slots.current.get(id)?.firstElementChild : null
      if (id && bubble && bubble.getBoundingClientRect().width >= full - 1) onSettled(id)
    }
  })

  if (drafts.length === 0) return null
  return (
    <div aria-hidden="true" style={hidden}>
      <div ref={fullRef}>
        <ChatMessageItem
          message={{ ...drafts[0], clientId: undefined, messageId: 'draft-width', content: FULL_WIDTH_TEXT }}
          onOpenFile={noop}
          onOpenFolder={noop}
        />
      </div>
      {drafts.map(draft => (
        <div
          key={draft.clientId}
          ref={el => {
            if (!draft.clientId) return
            if (el) slots.current.set(draft.clientId, el)
            else slots.current.delete(draft.clientId)
          }}
        >
          <ChatMessageItem message={draft} onOpenFile={noop} onOpenFolder={noop} />
        </div>
      ))}
    </div>
  )
}
