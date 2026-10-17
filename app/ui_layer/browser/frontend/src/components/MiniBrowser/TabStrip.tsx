import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Bot, Globe, Hand, Loader2, Plus } from 'lucide-react'
import { IconButton } from '../../components/ui'
import { ChromeTabs, type ChromeTab } from '../../components/ui/ChromeTabs'
import type { MiniBrowserTab } from '../../types'
import { useTabLabels } from './useTabLabels'
import styles from './TabStrip.module.css'

interface TabStripProps {
  /** The chat session whose browser the tabs are in. */
  sessionId: string
  tabs: MiniBrowserTab[]
  viewedTabId: string | null
  onSwitch(tabId: string): void
  onClose(tab: MiniBrowserTab): void
  onNew(): void
}

/** A site's icon; the generic globe when it has none or it fails to draw. */
function SiteIcon({ src }: { src: string | null }) {
  const [failed, setFailed] = useState<string | null>(null)
  if (!src || failed === src) return <Globe size={13} />
  return (
    <img
      className={styles.favicon}
      src={src}
      alt=""
      draggable={false}
      onError={() => setFailed(src)}
    />
  )
}

/**
 * A chat's browser tabs, drawn like Chrome's (ChromeTabs) above the toolbar,
 * where the viewed tab takes the toolbar's color and flows into it. Each tab
 * shows its site icon, or its state in its place (loading/agent working,
 * crashed, held by you), its title, and an agent mark when an agent uses it
 * (who, in its tooltip). "+" opens a new tab.
 */
export function TabStrip({ sessionId, tabs, viewedTabId, onSwitch, onClose, onNew }: TabStripProps) {
  const { t } = useTranslation(['minibrowser', 'common'])
  const { ownerName, tabTitle } = useTabLabels(sessionId)

  const items: ChromeTab[] = tabs.map(tab => {
    const title = tabTitle(tab)
    const owner = ownerName(tab)
    // The user holds an agent's tab: its agent waits until handed back, so
    // the tab says so (easy to find again from another tab).
    const userHolds = tab.userControl && tab.ownerKind !== 'user'
    const agentWorking = tab.busy && tab.ownerKind !== 'user' && !userHolds
    let icon: React.ReactNode
    let state = ''
    if (tab.crashed) {
      icon = <AlertTriangle size={13} className={styles.crashedIcon} />
      state = t('minibrowser:tabs.crashed')
    } else if (userHolds) {
      icon = <Hand size={13} />
      state = t('minibrowser:tabs.userControl')
    } else if (tab.loading || agentWorking) {
      icon = <Loader2 size={13} className={`${styles.spin} ${agentWorking ? styles.busyIcon : ''}`} />
      state = agentWorking ? t('minibrowser:tabs.busy') : t('minibrowser:tabs.loading')
    } else {
      icon = <SiteIcon src={tab.favicon} />
    }
    const ownerText = t('minibrowser:tabs.ownerTooltip', { owner })
    return {
      id: tab.id,
      title,
      icon,
      tooltip: [title, tab.url !== 'about:blank' ? tab.url : '', ownerText, userHolds ? state : '']
        .filter(Boolean)
        .join('\n'),
      description: [state, ownerText].filter(Boolean).join('. '),
      marks: tab.ownerKind !== 'user' && (
        <span className={styles.agentMark} aria-hidden="true">
          <Bot size={13} />
        </span>
      ),
      className: agentWorking ? styles.tabBusy : undefined,
      closeLabel: t('minibrowser:tabs.closeNamed', { title }),
    }
  })

  return (
    <ChromeTabs
      label={t('minibrowser:tabs.label')}
      tabs={items}
      selectedId={viewedTabId}
      onSelect={onSwitch}
      onClose={id => {
        const tab = tabs.find(item => item.id === id)
        if (tab) onClose(tab)
      }}
      closeTitle={t('minibrowser:tabs.close')}
      after={
        <IconButton
          type="button"
          size="sm"
          icon={<Plus />}
          onClick={onNew}
          aria-label={t('minibrowser:tabs.newTab')}
          tooltip={t('minibrowser:tabs.newTab')}
        />
      }
    />
  )
}
