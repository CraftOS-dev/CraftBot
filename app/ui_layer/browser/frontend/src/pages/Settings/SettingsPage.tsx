import { useState } from 'react'
import styles from './SettingsPage.module.css'
import { tourAnchorProps, useTourEnvAction, type TourAnchorId } from '../../tour'
import { SettingsCategory, categories } from './types'

// Settings tabs the guided tour highlights individually.
const TAB_TOUR_ANCHORS: Partial<Record<SettingsCategory, TourAnchorId>> = {
  proactive: 'settings-proactive',
  skills: 'settings-skills',
  integrations: 'settings-integrations',
}
import { GeneralSettings } from './GeneralSettings'
import { ProactiveSettings } from './ProactiveSettings'
import { MemorySettings } from './MemorySettings'
import { ModelSettings } from './ModelSettings'
import { MCPSettings } from './MCPSettings'
import { SkillsSettings } from './SkillsSettings'
import { IntegrationsSettings } from './IntegrationsSettings'
import { LivingUISettings } from './LivingUISettings'

export function SettingsPage() {
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>('general')

  // Let the guided tour open a specific tab so its panel is shown, not just its
  // rail button highlighted.
  useTourEnvAction('openSettingsTab', (arg) => {
    if (arg && categories.some(c => c.id === arg)) {
      setActiveCategory(arg as SettingsCategory)
    }
  })

  const renderSettingsContent = () => {
    switch (activeCategory) {
      case 'general':
        return <GeneralSettings />
      case 'proactive':
        return <ProactiveSettings />
      case 'memory':
        return <MemorySettings />
      case 'model':
        return <ModelSettings />
      case 'mcps':
        return <MCPSettings />
      case 'skills':
        return <SkillsSettings />
      case 'integrations':
        return <IntegrationsSettings />
      case 'living_ui':
        return <LivingUISettings />
      default:
        return null
    }
  }

  return (
    <div className={styles.settingsPage}>
      {/* Category rail — sits flush against the content, no separate
          background/border. Compact icon + label, no description/chevron. */}
      <nav className={styles.sidebar}>
        <div className={styles.categoryList} {...tourAnchorProps('settings-categories')}>
          {categories.map(cat => {
            const tourAnchor = TAB_TOUR_ANCHORS[cat.id]
            return (
              <button
                key={cat.id}
                className={`${styles.categoryItem} ${activeCategory === cat.id ? styles.active : ''}`}
                onClick={() => setActiveCategory(cat.id)}
                {...(tourAnchor ? tourAnchorProps(tourAnchor) : {})}
              >
                <span className={styles.categoryIcon}>{cat.icon}</span>
                <span className={styles.categoryLabel}>{cat.label}</span>
              </button>
            )
          })}
        </div>
      </nav>

      {/* Content */}
      <div className={styles.content}>
        {renderSettingsContent()}
      </div>
    </div>
  )
}
