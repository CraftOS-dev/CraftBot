import React, {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  Copy,
  ExternalLink,
  Globe,
  KeyRound,
  LocateFixed,
  Lock,
  MoreHorizontal,
  Power,
  RotateCw,
  Search,
  ShieldCheck,
  ShieldOff,
  StopCircle,
  X,
} from 'lucide-react'
import { Button, IconButton } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import type { SessionRunState } from '../../store/slices/agentSlice'
import type { MiniBrowserError, MiniBrowserTab } from '../../types'
import { copyText } from './clipboard'
import { useErrorText } from './useErrorText'
import { isBlankUrl, isWebUrl } from './useTabLabels'
import styles from './Toolbar.module.css'

// How long an ad-blocker change may stay unconfirmed before the toggle
// re-enables (the state broadcast normally confirms it at once).
const ADBLOCK_PENDING_MS = 8000

/** Enabled menu items the current width shows (narrow-only items are hidden
 *  by the container query on a wide toolbar). */
function menuEntries(menu: HTMLElement | null): HTMLButtonElement[] {
  if (!menu) return []
  return Array.from(menu.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]:not(:disabled)'))
    .filter(item => item.offsetParent !== null)
}

export interface ToolbarHandle {
  /** Focus the address bar with its text selected. */
  focusAddress(): void
}

export interface StopTarget {
  /** Session whose run drives the viewed tab. */
  sessionId: string
  runState: SessionRunState
}

interface ToolbarProps {
  tab: MiniBrowserTab | null
  follow: boolean
  adblock: boolean | null
  /** The browser is running (or starting), so "Close browser" applies. */
  browserOpen: boolean
  navError: MiniBrowserError | null
  stopTarget: StopTarget | null
  onNavigate(text: string): void
  onHistory(action: 'back' | 'forward' | 'reload' | 'stop'): void
  onFollow(next: boolean): void
  onAdblock(next: boolean): void
  onOpenPasswords(): void
  onCloseBrowser(): void
  onStopAgent(): void
  onDismissNavError(): void
  /** An address was submitted: the page takes the keyboard. */
  onSubmitted(): void
}

type MenuItem = {
  id: string
  label: string
  icon: React.ReactNode
  onSelect(): void
  disabled?: boolean
  /** Shown only when the toolbar is too narrow for the item's own button. */
  collapsed?: 'narrow' | 'narrowest'
  checked?: boolean
  danger?: boolean
  title?: string
}

/**
 * Back / forward / reload, the address bar, and the browser's toggles.
 * Collapses with container queries: secondary buttons move into the "…" menu
 * when the panel is narrow.
 */
export const Toolbar = forwardRef<ToolbarHandle, ToolbarProps>(function Toolbar(props, ref) {
  const {
    tab,
    follow,
    adblock,
    browserOpen,
    navError,
    stopTarget,
    onNavigate,
    onHistory,
    onFollow,
    onAdblock,
    onOpenPasswords,
    onCloseBrowser,
    onStopAgent,
    onDismissNavError,
    onSubmitted,
  } = props
  const { t } = useTranslation(['minibrowser', 'common'])
  const { showToast } = useToast()
  const errorText = useErrorText()
  const menuId = useId()

  // ── Address bar ────────────────────────────────────────────────────
  const inputRef = useRef<HTMLInputElement>(null)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  // A click that focuses the field must not undo its select-all on mouseup.
  const selectOnMouseUpRef = useRef(false)

  const url = tab?.url ?? ''
  const shownUrl = isBlankUrl(url) ? '' : url
  const value = editing ? text : shownUrl

  const focusAddress = useCallback(() => {
    const input = inputRef.current
    if (!input) return
    input.focus()
    input.select()
  }, [])

  useImperativeHandle(ref, () => ({ focusAddress }), [focusAddress])

  const onAddressFocus = (e: React.FocusEvent<HTMLInputElement>) => {
    setText(shownUrl)
    setEditing(true)
    selectOnMouseUpRef.current = true
    e.currentTarget.select()
  }

  const onAddressMouseUp = (e: React.MouseEvent<HTMLInputElement>) => {
    if (!selectOnMouseUpRef.current) return
    selectOnMouseUpRef.current = false
    // Keep the whole address selected unless the user dragged a selection.
    if (e.currentTarget.selectionStart === e.currentTarget.selectionEnd) e.preventDefault()
  }

  const onAddressKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Escape') return
    e.preventDefault()
    if (text !== shownUrl) {
      // First Escape reverts the edit, the second leaves the field.
      setText(shownUrl)
      requestAnimationFrame(() => inputRef.current?.select())
    } else {
      e.currentTarget.blur()
    }
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const target = text.trim()
    if (!target) return
    onNavigate(target)
    setEditing(false)
    inputRef.current?.blur()
    onSubmitted()
  }

  // ── Ad blocker: unknown until reported, pending until confirmed ─────
  const [adblockPending, setAdblockPending] = useState<boolean | null>(null)
  useEffect(() => {
    if (adblockPending === null) return
    if (adblock === adblockPending) {
      setAdblockPending(null)
      return
    }
    const timer = window.setTimeout(() => setAdblockPending(null), ADBLOCK_PENDING_MS)
    return () => window.clearTimeout(timer)
  }, [adblock, adblockPending])

  const toggleAdblock = () => {
    if (adblock === null || adblockPending !== null) return
    setAdblockPending(!adblock)
    onAdblock(!adblock)
  }

  const adblockShown = adblockPending ?? adblock
  const adblockLabel =
    adblock === null ? t('minibrowser:toolbar.adblockUnknown')
      : adblockPending !== null ? t('minibrowser:toolbar.adblockPending')
        : adblock ? t('minibrowser:toolbar.adblockOnHint') : t('minibrowser:toolbar.adblockOffHint')

  // ── Overflow menu ──────────────────────────────────────────────────
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)

  const closeMenu = useCallback((returnFocus: boolean) => {
    setMenuOpen(false)
    if (returnFocus) menuButtonRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (menuRef.current?.contains(target) || menuButtonRef.current?.contains(target)) return
      setMenuOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    // Land on the first item.
    menuEntries(menuRef.current)[0]?.focus()
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [menuOpen])

  const onMenuKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const items = menuEntries(menuRef.current)
    const index = items.indexOf(document.activeElement as HTMLButtonElement)
    if (e.key === 'Escape' || e.key === 'Tab') {
      if (e.key === 'Escape') e.preventDefault()
      closeMenu(e.key === 'Escape')
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      items[(index + 1) % items.length]?.focus()
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      items[(index - 1 + items.length) % items.length]?.focus()
    } else if (e.key === 'Home') {
      e.preventDefault()
      items[0]?.focus()
    } else if (e.key === 'End') {
      e.preventDefault()
      items[items.length - 1]?.focus()
    }
  }

  const webUrl = isWebUrl(url) ? url : ''

  const copyLink = async () => {
    if (!webUrl) return
    const ok = await copyText(webUrl)
    if (ok) showToast('success', t('minibrowser:toolbar.linkCopied'))
    else showToast('error', t('minibrowser:toolbar.copyFailed'))
  }

  const openExternal = () => {
    if (!webUrl) return
    window.open(webUrl, '_blank', 'noopener,noreferrer')
  }

  const menuItems: MenuItem[] = [
    {
      id: 'forward',
      label: t('minibrowser:toolbar.forward'),
      icon: <ArrowRight size={14} />,
      onSelect: () => onHistory('forward'),
      disabled: !tab?.canGoForward,
      collapsed: 'narrowest',
    },
    {
      id: 'follow',
      label: t('minibrowser:toolbar.follow'),
      icon: <LocateFixed size={14} />,
      onSelect: () => onFollow(!follow),
      checked: follow,
      collapsed: 'narrow',
    },
    {
      id: 'adblock',
      label: t('minibrowser:toolbar.adblock'),
      icon: adblockShown ? <ShieldCheck size={14} /> : <ShieldOff size={14} />,
      onSelect: toggleAdblock,
      checked: !!adblockShown,
      disabled: adblock === null || adblockPending !== null,
      collapsed: 'narrow',
    },
    {
      id: 'passwords',
      label: t('minibrowser:toolbar.passwords'),
      icon: <KeyRound size={14} />,
      onSelect: onOpenPasswords,
      collapsed: 'narrow',
    },
    {
      id: 'copy',
      label: t('minibrowser:toolbar.copyLink'),
      icon: <Copy size={14} />,
      onSelect: () => { void copyLink() },
      disabled: !webUrl,
    },
    {
      id: 'external',
      label: t('minibrowser:toolbar.openExternal'),
      icon: <ExternalLink size={14} />,
      onSelect: openExternal,
      disabled: !webUrl,
      title: t('minibrowser:toolbar.openExternalHint'),
    },
    {
      id: 'close',
      label: t('minibrowser:toolbar.closeBrowser'),
      icon: <Power size={14} />,
      onSelect: onCloseBrowser,
      disabled: !browserOpen,
      danger: true,
    },
  ]

  // ── Security indicator ─────────────────────────────────────────────
  let securityIcon: React.ReactNode
  let securityLabel = ''
  if (editing) {
    securityIcon = <Search size={14} />
  } else if (/^https:\/\//i.test(url)) {
    securityIcon = <Lock size={13} />
    securityLabel = t('minibrowser:toolbar.secure')
  } else if (/^http:\/\//i.test(url)) {
    securityIcon = <AlertTriangle size={13} className={styles.insecureIcon} />
    securityLabel = t('minibrowser:toolbar.notSecure')
  } else {
    securityIcon = <Globe size={14} />
  }

  const navErrorText = navError ? errorText(navError) : null
  const stopping = stopTarget?.runState === 'stopping'

  return (
    <div className={styles.container}>
      <div className={styles.toolbar} role="toolbar" aria-label={t('minibrowser:toolbar.label')}>
        <div className={styles.navButtons}>
          <IconButton
            type="button"
            size="md"
            icon={<ArrowLeft />}
            onClick={() => onHistory('back')}
            disabled={!tab?.canGoBack}
            aria-label={t('minibrowser:toolbar.back')}
            tooltip={t('minibrowser:toolbar.back')}
          />
          <IconButton
            type="button"
            size="md"
            className={styles.forwardButton}
            icon={<ArrowRight />}
            onClick={() => onHistory('forward')}
            disabled={!tab?.canGoForward}
            aria-label={t('minibrowser:toolbar.forward')}
            tooltip={t('minibrowser:toolbar.forward')}
          />
          {tab?.loading ? (
            <IconButton
              type="button"
              size="md"
              icon={<X />}
              onClick={() => onHistory('stop')}
              aria-label={t('minibrowser:toolbar.stopLoading')}
              tooltip={t('minibrowser:toolbar.stopLoading')}
            />
          ) : (
            <IconButton
              type="button"
              size="md"
              icon={<RotateCw />}
              onClick={() => onHistory('reload')}
              disabled={!tab}
              aria-label={t('minibrowser:toolbar.reload')}
              tooltip={t('minibrowser:toolbar.reload')}
            />
          )}
        </div>

        <form className={styles.addressForm} onSubmit={submit} role="search">
          <span
            className={styles.securityIcon}
            title={securityLabel || undefined}
            aria-label={securityLabel || undefined}
            role={securityLabel ? 'img' : undefined}
            aria-hidden={securityLabel ? undefined : true}
          >
            {securityIcon}
          </span>
          <input
            ref={inputRef}
            className={styles.address}
            type="text"
            value={value}
            onChange={e => {
              setText(e.target.value)
              setEditing(true)
            }}
            onFocus={onAddressFocus}
            onBlur={() => setEditing(false)}
            onMouseUp={onAddressMouseUp}
            onKeyDown={onAddressKeyDown}
            placeholder={t('minibrowser:toolbar.addressPlaceholder')}
            aria-label={t('minibrowser:toolbar.address')}
            inputMode="url"
            enterKeyHint="go"
            autoCapitalize="off"
            autoCorrect="off"
            autoComplete="off"
            spellCheck={false}
            data-1p-ignore=""
            data-lpignore="true"
            data-form-type="other"
          />
        </form>

        <div className={styles.actions}>
          <IconButton
            type="button"
            size="md"
            className={styles.wideOnly}
            icon={<LocateFixed />}
            active={follow}
            onClick={() => onFollow(!follow)}
            aria-pressed={follow}
            aria-label={t('minibrowser:toolbar.follow')}
            tooltip={follow ? t('minibrowser:toolbar.followOnHint') : t('minibrowser:toolbar.followOffHint')}
          />
          <IconButton
            type="button"
            size="md"
            className={`${styles.wideOnly} ${adblockPending !== null ? styles.pending : ''}`}
            icon={adblockShown === false ? <ShieldOff /> : <ShieldCheck />}
            active={!!adblockShown}
            onClick={toggleAdblock}
            disabled={adblock === null || adblockPending !== null}
            aria-pressed={adblock === null ? undefined : !!adblockShown}
            aria-label={t('minibrowser:toolbar.adblock')}
            tooltip={adblockLabel}
          />
          <IconButton
            type="button"
            size="md"
            className={styles.wideOnly}
            icon={<KeyRound />}
            onClick={onOpenPasswords}
            aria-label={t('minibrowser:toolbar.passwords')}
            tooltip={t('minibrowser:toolbar.passwords')}
          />
          <div className={styles.menuAnchor}>
            <IconButton
              ref={menuButtonRef}
              type="button"
              size="md"
              icon={<MoreHorizontal />}
              active={menuOpen}
              onClick={() => setMenuOpen(open => !open)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-controls={menuOpen ? menuId : undefined}
              aria-label={t('minibrowser:toolbar.more')}
              tooltip={t('minibrowser:toolbar.more')}
            />
            {menuOpen && (
              <div
                ref={menuRef}
                id={menuId}
                className={styles.menu}
                role="menu"
                aria-label={t('minibrowser:toolbar.more')}
                onKeyDown={onMenuKeyDown}
              >
                {menuItems.map(item => (
                  <button
                    key={item.id}
                    type="button"
                    role={item.checked === undefined ? 'menuitem' : 'menuitemcheckbox'}
                    aria-checked={item.checked}
                    className={[
                      styles.menuItem,
                      item.collapsed === 'narrow' ? styles.narrowOnly : '',
                      item.collapsed === 'narrowest' ? styles.narrowestOnly : '',
                      item.danger ? styles.menuItemDanger : '',
                    ].filter(Boolean).join(' ')}
                    disabled={item.disabled}
                    title={item.title}
                    onClick={() => {
                      closeMenu(true)
                      item.onSelect()
                    }}
                  >
                    <span className={styles.menuIcon}>{item.icon}</span>
                    <span className={styles.menuLabel}>{item.label}</span>
                    {item.checked !== undefined && (
                      <span className={styles.menuCheck} aria-hidden="true">
                        {item.checked && <Check size={14} />}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
          {stopTarget && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className={styles.stopButton}
              icon={<StopCircle size={14} />}
              loading={stopping}
              onClick={onStopAgent}
              title={stopping ? t('minibrowser:toolbar.stopping') : t('minibrowser:toolbar.stopAgentHint')}
              aria-label={stopping ? t('minibrowser:toolbar.stopping') : t('minibrowser:toolbar.stopAgent')}
            >
              <span className={styles.stopLabel}>
                {stopping ? t('minibrowser:toolbar.stopping') : t('minibrowser:toolbar.stopAgent')}
              </span>
            </Button>
          )}
        </div>
      </div>

      {navErrorText && (
        <div className={styles.navError} role="alert">
          <AlertCircle size={15} className={styles.navErrorIcon} />
          <div className={styles.navErrorText}>
            <strong>{navErrorText.title}</strong>
            <span>{navErrorText.message}</span>
            {navErrorText.detail && <span className={styles.navErrorDetail}>{navErrorText.detail}</span>}
          </div>
          <IconButton
            type="button"
            size="sm"
            icon={<X />}
            onClick={onDismissNavError}
            aria-label={t('minibrowser:toolbar.dismiss')}
            tooltip={t('minibrowser:toolbar.dismiss')}
          />
        </div>
      )}
    </div>
  )
})
