import React, { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Globe, Loader2, Plus, X } from 'lucide-react'
import { IconButton } from '../../components/ui'
import type { MiniBrowserTab } from '../../types'
import { useTabLabels } from './useTabLabels'
import styles from './TabStrip.module.css'

interface TabStripProps {
  tabs: MiniBrowserTab[]
  viewedTabId: string | null
  onSwitch(tabId: string): void
  onClose(tab: MiniBrowserTab): void
  onNew(): void
}

const MIDDLE_BUTTON = 1

/**
 * Browser tabs. Each tab shows its title, who uses it (you, the Main chat, a
 * chat's title, a sub-agent) and its state (loading/agent working, crashed).
 * Keyboard: ←/→/Home/End move between tabs, Enter/Space opens one, Delete
 * closes it. Middle-click closes too. "+" is always there.
 */
export function TabStrip({ tabs, viewedTabId, onSwitch, onClose, onNew }: TabStripProps) {
  const { t } = useTranslation(['minibrowser', 'common'])
  const { ownerName, tabTitle } = useTabLabels()
  const listRef = useRef<HTMLDivElement>(null)

  // Keep the viewed tab in sight when it changes (e.g. following an agent).
  useEffect(() => {
    if (!viewedTabId) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-tab-id="${CSS.escape(viewedTabId)}"]`)
    el?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [viewedTabId])

  const focusableIndex = Math.max(0, tabs.findIndex(tab => tab.id === viewedTabId))

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
      if (tab) onClose(tab)
      return
    }
    if (next === -1) return
    e.preventDefault()
    buttons[next]?.focus()
  }

  return (
    <div className={styles.strip}>
      <div
        ref={listRef}
        className={styles.tabs}
        role="tablist"
        aria-label={t('minibrowser:tabs.label')}
        onKeyDown={onListKeyDown}
      >
        {tabs.map((tab, index) => {
          const selected = tab.id === viewedTabId
          const title = tabTitle(tab)
          const owner = ownerName(tab)
          const agentWorking = tab.busy && tab.ownerKind !== 'user'
          let icon: React.ReactNode
          let state = ''
          if (tab.crashed) {
            icon = <AlertTriangle size={13} className={styles.crashedIcon} />
            state = t('minibrowser:tabs.crashed')
          } else if (tab.loading || agentWorking) {
            icon = <Loader2 size={13} className={`${styles.spin} ${agentWorking ? styles.busyIcon : ''}`} />
            state = agentWorking ? t('minibrowser:tabs.busy') : t('minibrowser:tabs.loading')
          } else {
            icon = <Globe size={13} />
          }
          const tooltip = [title, tab.url !== 'about:blank' ? tab.url : '', t('minibrowser:tabs.ownerTooltip', { owner })]
            .filter(Boolean)
            .join('\n')
          return (
            <div
              key={tab.id}
              data-tab-id={tab.id}
              className={[
                styles.tab,
                selected ? styles.tabSelected : '',
                agentWorking ? styles.tabBusy : '',
              ].filter(Boolean).join(' ')}
              onMouseDown={e => {
                // Middle-click closes (and must not start autoscroll).
                if (e.button === MIDDLE_BUTTON) e.preventDefault()
              }}
              onAuxClick={e => {
                if (e.button !== MIDDLE_BUTTON) return
                e.preventDefault()
                onClose(tab)
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
                  if (!selected) onSwitch(tab.id)
                }}
                title={tooltip}
              >
                <span className={styles.tabIcon}>{icon}</span>
                <span className={styles.tabTitle}>{title}</span>
                {state && <span className="sr-only">{state}</span>}
                <span className={`${styles.owner} ${tab.ownerKind === 'user' ? styles.ownerUser : ''}`}>
                  {owner}
                </span>
              </button>
              <button
                type="button"
                className={styles.close}
                tabIndex={-1}
                onClick={() => onClose(tab)}
                aria-label={t('minibrowser:tabs.closeNamed', { title })}
                title={t('minibrowser:tabs.close')}
              >
                <X size={12} />
              </button>
            </div>
          )
        })}
      </div>
      <IconButton
        type="button"
        size="sm"
        className={styles.newTab}
        icon={<Plus />}
        onClick={onNew}
        aria-label={t('minibrowser:tabs.newTab')}
        tooltip={t('minibrowser:tabs.newTab')}
      />
    </div>
  )
}
