import React, { useEffect, useRef, type ReactNode, type Ref } from 'react'
import { X } from 'lucide-react'
import styles from './ChromeTabs.module.css'

export interface ChromeTab {
  id: string
  title: string
  /** In the icon's place: a site icon, a kind, or a state (loading, ...). */
  icon: ReactNode
  tooltip?: string
  /** After the title (e.g. an agent mark). */
  marks?: ReactNode
  /** Read with the tab by screen readers, not shown. */
  description?: string
  /** An extra class on the tab, for the consumer's own state styling. */
  className?: string
  /** The close button's accessible name. */
  closeLabel: string
}

interface ChromeTabsProps {
  /** The tab list's accessible name. */
  label: string
  tabs: ChromeTab[]
  selectedId: string | null
  onSelect(id: string): void
  onClose(id: string): void
  /** The close buttons' tooltip. */
  closeTitle: string
  /** Right after the last tab (Chrome's "+"). */
  after?: ReactNode
  /** The strip's own buttons, at its right end. */
  actions?: ReactNode
  /** The actions container: other components may render buttons into it. */
  actionsRef?: Ref<HTMLDivElement>
}

const MIDDLE_BUTTON = 1

/**
 * Tabs drawn like Chrome's (the shared look of the chat's browser and output
 * panels). Keyboard: ←/→/Home/End move between tabs, Enter/Space selects
 * one, Delete closes it. Middle-click closes too. The selected tab is kept
 * in sight when it changes.
 */
export function ChromeTabs({
  label,
  tabs,
  selectedId,
  onSelect,
  onClose,
  closeTitle,
  after,
  actions,
  actionsRef,
}: ChromeTabsProps) {
  const listRef = useRef<HTMLDivElement>(null)

  // Only the tab list scrolls (scrollIntoView would also scroll the panels
  // around it, even ones that clip their overflow).
  useEffect(() => {
    const list = listRef.current
    if (!selectedId || !list) return
    const el = list.querySelector<HTMLElement>(`[data-tab-id="${CSS.escape(selectedId)}"]`)
    if (!el) return
    const listBox = list.getBoundingClientRect()
    const tabBox = el.getBoundingClientRect()
    if (tabBox.left < listBox.left) list.scrollLeft -= listBox.left - tabBox.left
    else if (tabBox.right > listBox.right) list.scrollLeft += tabBox.right - listBox.right
  }, [selectedId])

  const focusableIndex = Math.max(0, tabs.findIndex(tab => tab.id === selectedId))

  const onListKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const buttons = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? [])
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (index === -1) return
    let next = -1
    if (e.key === 'ArrowRight') next = (index + 1) % buttons.length
    else if (e.key === 'ArrowLeft') next = (index - 1 + buttons.length) % buttons.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = buttons.length - 1
    else if (e.key === 'Delete') {
      e.preventDefault()
      const tab = tabs[index]
      if (tab) onClose(tab.id)
      return
    }
    if (next === -1) return
    e.preventDefault()
    buttons[next]?.focus()
  }

  return (
    <div className={styles.strip}>
      <div ref={listRef} className={styles.tabs} role="tablist" aria-label={label} onKeyDown={onListKeyDown}>
        {tabs.map((tab, index) => {
          const selected = tab.id === selectedId
          return (
            <div
              key={tab.id}
              data-tab-id={tab.id}
              className={[styles.tab, selected ? styles.tabSelected : '', tab.className ?? '']
                .filter(Boolean)
                .join(' ')}
              onMouseDown={e => {
                // Middle-click closes (and must not start autoscroll).
                if (e.button === MIDDLE_BUTTON) e.preventDefault()
              }}
              onAuxClick={e => {
                if (e.button !== MIDDLE_BUTTON) return
                e.preventDefault()
                onClose(tab.id)
              }}
            >
              <button
                type="button"
                role="tab"
                aria-selected={selected}
                aria-keyshortcuts="Delete"
                tabIndex={index === focusableIndex ? 0 : -1}
                className={styles.tabButton}
                onClick={() => {
                  if (!selected) onSelect(tab.id)
                }}
                title={tab.tooltip ?? tab.title}
              >
                <span className={styles.tabIcon}>{tab.icon}</span>
                <span className={styles.tabTitle}>{tab.title}</span>
                {tab.description && <span className="sr-only">{tab.description}</span>}
                {tab.marks}
              </button>
              <button
                type="button"
                className={styles.close}
                tabIndex={-1}
                onClick={() => onClose(tab.id)}
                aria-label={tab.closeLabel}
                title={closeTitle}
              >
                <X size={14} />
              </button>
            </div>
          )
        })}
      </div>
      {after && <div className={styles.after}>{after}</div>}
      {(actions || actionsRef) && (
        <div ref={actionsRef} className={styles.actions}>
          {actions}
        </div>
      )}
    </div>
  )
}
