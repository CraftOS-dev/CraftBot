import { useState } from 'react'
import styles from './SettingsPage.module.css'
import { SettingsCategory, categories } from './types'
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
        <div className={styles.categoryList}>
          {categories.map(cat => (
            <button
              key={cat.id}
              className={`${styles.categoryItem} ${activeCategory === cat.id ? styles.active : ''}`}
              onClick={() => setActiveCategory(cat.id)}
            >
              <span className={styles.categoryIcon}>{cat.icon}</span>
              <span className={styles.categoryLabel}>{cat.label}</span>
            </button>
          ))}
        </div>
      </nav>

      {/* Content */}
      <div className={styles.content}>
        {renderSettingsContent()}
      </div>
    </div>
  )
}
