import { Fragment, useState, type CSSProperties, type ReactNode, type Ref } from 'react'
import { ChevronRight, Copy } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui/Button'
import styles from './SettingsPage.module.css'

// Extracted from the original ProjectCard so both app runtimes use the same UI.
export const appSectionLabelStyle: CSSProperties = {
  fontSize: '10px', fontWeight: 'var(--font-semibold)', color: 'var(--text-tertiary)',
  textTransform: 'uppercase', letterSpacing: '0.08em',
}
export const appSettingRowStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  gap: 'var(--space-3)', padding: 'var(--space-2) 0',
}
export const appSettingHintStyle: CSSProperties = {
  fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5,
}

export function AppSettingsCard({ name, status, statusColor, active, expanded, onToggle, actions, children, cardRef }: {
  name: string; status: string; statusColor: string; active?: boolean; expanded: boolean
  onToggle: () => void; actions?: ReactNode; children?: ReactNode; cardRef?: Ref<HTMLElement>
}) {
  return <article ref={cardRef} aria-label={`${name} settings`} style={{
    display: 'flex', flexDirection: 'column', background: 'var(--bg-tertiary)',
    border: '1px solid var(--border-primary)', borderRadius: 'var(--radius-md)', overflow: 'hidden',
  }}>
    <div role="button" tabIndex={0} aria-expanded={expanded} onClick={onToggle}
      onKeyDown={event => {
        if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault(); onToggle()
        }
      }}
      style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', padding: 'var(--space-3)', cursor: 'pointer', userSelect: 'none' }}>
      <ChevronRight size={14} style={{ color: 'var(--text-muted)', transition: 'transform 0.15s', transform: expanded ? 'rotate(90deg)' : 'none', flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 'var(--text-base)', fontWeight: 'var(--font-semibold)', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginTop: 4 }}>
          <span className={`${styles.statusDot} ${active ? styles.statusDotPulse : ''}`} style={{ background: statusColor }} />
          <span style={{ fontSize: 'var(--text-xs)', color: statusColor, fontWeight: 'var(--font-medium)' }}>{status}</span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)', flexShrink: 0 }} onClick={event => event.stopPropagation()}>
        {actions}
      </div>
    </div>
    {expanded && children}
  </article>
}

export function AppSettingsInfo({ rows, path }: { rows: { label: string; value: ReactNode }[]; path: string }) {
  const { t } = useTranslation('settings')
  const valueStyle: CSSProperties = { fontSize: 'var(--text-sm)', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', minWidth: 0 }
  const labelStyle: CSSProperties = { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }
  return <div style={{
    padding: 'var(--space-3)', background: 'var(--bg-primary)', borderTop: '1px solid var(--border-primary)',
    display: 'grid', gridTemplateColumns: '110px minmax(0, 1fr)', rowGap: 'var(--space-2)', columnGap: 'var(--space-3)', alignItems: 'center',
  }}>
    {rows.map(row => <Fragment key={row.label}><span style={labelStyle}>{row.label}</span><span style={valueStyle}>{row.value}</span></Fragment>)}
    <span style={labelStyle}>{t('agentApp.path')}</span>
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', minWidth: 0 }}>
      <span title={path} style={{ ...valueStyle, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{path}</span>
      <Button size="sm" variant="ghost" icon={<Copy size={12} />} onClick={() => void navigator.clipboard.writeText(path)} title={t('agentApp.copyPath')} />
    </div>
  </div>
}

export function AppSettingsSection({ title, children, collapsible = false }: { title: string; children: ReactNode; collapsible?: boolean }) {
  const [open, setOpen] = useState(false)
  return <section aria-label={title} style={{ padding: 'var(--space-3)', borderTop: '1px solid var(--border-primary)' }}>
    {collapsible ? <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)} style={{
      ...appSectionLabelStyle, display: 'flex', alignItems: 'center', gap: 'var(--space-2)', border: 0, padding: 0,
      background: 'none', cursor: 'pointer', marginBottom: open ? 'var(--space-2)' : 0,
    }}><ChevronRight size={12} style={{ transform: open ? 'rotate(90deg)' : undefined }} />{title}</button>
      : <div style={{ ...appSectionLabelStyle, marginBottom: 'var(--space-2)' }}>{title}</div>}
    {(!collapsible || open) && children}
  </section>
}

export function AppSettingsToggle({ label, description, checked, disabled, onChange, divider = false, children }: {
  label: string; description?: string; checked: boolean; disabled?: boolean; onChange: (value: boolean) => void; divider?: boolean; children?: ReactNode
}) {
  return <div style={{ ...appSettingRowStyle, borderTop: divider ? '1px solid var(--border-primary)' : 'none' }}>
    <div className={styles.toggleInfo}>
      <span className={styles.toggleLabel}>{label}</span>
      {description && <span className={styles.toggleDesc}>{description}</span>}
      {children}
    </div>
    <input type="checkbox" className={styles.toggle} aria-label={label} checked={checked} disabled={disabled}
      style={disabled ? { opacity: 0.5, cursor: 'not-allowed' } : undefined} onChange={event => onChange(event.target.checked)} />
  </div>
}
