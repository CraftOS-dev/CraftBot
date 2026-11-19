import { useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { Box, X } from 'lucide-react'
import type { AppsPanelMode } from './ChatWorkspace'
import styles from './ChatWorkspace.module.css'

/**
 * The panel's Agent Apps button: the sidebar's cube until the chat has an
 * app, then that app's icon. With the chat's app hidden, pressing it shows
 * that app. Otherwise it opens a menu, styled like the sidebar's Agent Apps
 * flyout, of the installed apps to show or switch to, and Close once the chat
 * has an app. Arrow Down always opens the menu.
 */
export function AppPickerButton({ apps, shown, buttonRef, onPick, onClose }: {
  apps: AppsPanelMode
  /** The panel is showing this chat's app. */
  shown: boolean
  buttonRef: RefObject<HTMLButtonElement>
  onPick(projectId: string): void
  onClose(): void
}) {
  const { t } = useTranslation('chat')
  const menuId = useId()
  const root = useRef<HTMLSpanElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const { choices, selected } = apps
  const menuItems = () => Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('button') ?? [])

  useEffect(() => {
    if (!open) return
    // Opening focuses the chat's own app, else the first item.
    const current = menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
    ;(current ?? menuItems()[0])?.focus()
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  const dismiss = () => {
    setOpen(false)
    buttonRef.current?.focus()
  }
  const run = (action: () => void) => {
    dismiss()
    action()
  }
  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const buttons = menuItems()
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    const move = (to: number) => { event.preventDefault(); buttons[(to + buttons.length) % buttons.length]?.focus() }
    if (event.key === 'ArrowDown') move(index + 1)
    else if (event.key === 'ArrowUp') move(index - 1)
    else if (event.key === 'Home') move(0)
    else if (event.key === 'End') move(buttons.length - 1)
    else if (event.key === 'Escape') { event.preventDefault(); dismiss() }
    else if (event.key === 'Tab') setOpen(false)
  }

  return <span ref={root} className={styles.appPicker}>
    <button type="button" ref={buttonRef} onClick={() => {
      // The chat's app, hidden: bring it back. Otherwise (no app yet, or the
      // app on show) the menu picks, switches or closes it.
      if (!open && selected && !shown) onPick(selected.id)
      else setOpen(value => !value)
    }}
      onKeyDown={event => { if (event.key === 'ArrowDown' && !open) { event.preventDefault(); setOpen(true) } }}
      aria-label={t('apps.show')} title={selected?.title ?? t('apps.show')}
      aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} data-shown={shown}>
      {selected ? selected.icon : <Box size={16} />}
    </button>
    {open && <div ref={menu} id={menuId} role="menu" aria-label={t('apps.title')} className={styles.appMenu} onKeyDown={onMenuKeyDown}>
      {choices.length > 0
        ? <div className={styles.appMenuList}>
          {choices.map(choice => (
            <button key={choice.id} type="button" role="menuitemradio" aria-checked={choice.id === selected?.id}
              className={styles.appMenuItem} onClick={() => run(() => onPick(choice.id))}>
              <span className={styles.appMenuIcon}>{choice.icon}</span>
              <span className={styles.appMenuLabel}>{choice.title}</span>
            </button>
          ))}
        </div>
        : <p className={styles.appMenuEmpty} role="status">{apps.loaded ? t('apps.noInstalled') : t('apps.loading')}</p>}
      {selected && <>
        <div className={styles.appMenuDivider} role="separator" />
        <button type="button" role="menuitem" className={styles.appMenuItem} onClick={() => run(onClose)}>
          <span className={styles.appMenuIcon}><X size={14} /></span>
          <span className={styles.appMenuLabel}>{t('apps.close')}</span>
        </button>
      </>}
    </div>}
  </span>
}
