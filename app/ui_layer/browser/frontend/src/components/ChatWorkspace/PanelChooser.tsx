import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Globe, Layers3, Search } from 'lucide-react'
import styles from './PanelChooser.module.css'

interface Choice { id: string; title: string; icon: ReactNode }

/** The panel's opening page, not an overlay: choose content before creating a tab. */
export function PanelChooser({ browser, apps, outputs, loaded, onBrowser, onApp, onOutput }: {
  browser: boolean
  apps: Choice[]
  outputs: Choice[]
  loaded: boolean
  onBrowser(): void
  onApp(id: string): void
  onOutput(id: string): void
}) {
  const { t } = useTranslation('chat')
  const [query, setQuery] = useState('')
  const matches = (title: string) => title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  const matchingApps = apps.filter(item => matches(item.title))
  const matchingOutputs = outputs.filter(item => matches(item.title))
  const showBrowser = browser && matches(t('panel.browser'))
  const row = (item: Choice, open: () => void) => <button key={item.id} type="button" className={styles.choice} onClick={open}>
    {item.icon}<span>{item.title}</span>
  </button>
  return <div className={styles.chooser}>
    <h2>{t('panel.open')}</h2>
    <label className={styles.search}><Search size={16} /><input aria-label={t('panel.search')} placeholder={t('panel.search')} value={query} onChange={event => setQuery(event.target.value)} /></label>
    <div className={styles.choices}>
      {showBrowser && row({ id: 'browser', title: t('panel.browser'), icon: <Globe size={19} /> }, onBrowser)}
      {matchingApps.length > 0 && <section aria-label={t('panel.apps')}><h3>{t('panel.apps')}</h3>{matchingApps.map(item => row(item, () => onApp(item.id)))}</section>}
      {matchingOutputs.length > 0 && <section aria-label={t('panel.outputs')}><h3>{t('panel.outputs')}</h3>{matchingOutputs.map(item => row({ ...item, icon: item.icon ?? <Layers3 size={19} /> }, () => onOutput(item.id)))}</section>}
      {!loaded && <p role="status">{t('apps.loading')}</p>}
      {loaded && !showBrowser && !matchingApps.length && !matchingOutputs.length && <p role="status">{t('panel.noMatches')}</p>}
    </div>
  </div>
}
