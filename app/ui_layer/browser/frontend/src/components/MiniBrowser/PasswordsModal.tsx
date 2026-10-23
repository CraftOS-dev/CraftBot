import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertCircle,
  AlertTriangle,
  Globe,
  FileText,
  Code2,
  Plus,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Pencil,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { Badge, Button, ConfirmModal, IconButton, Modal, ModalBody, ModalFooter } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { formatDate } from '../../i18n/format'
import { useAppSelector } from '../../store/hooks'
import { RESOURCES, resourceSync, useResource } from '../../store/resources'
import {
  selectMiniBrowserVaultEntries,
  selectMiniBrowserVaultError,
  selectMiniBrowserVaultLoaded,
  selectMiniBrowserVaultResult,
  selectMiniBrowserVaultStatus,
} from '../../store/selectors/miniBrowser'
import type { CredentialKind, CredentialGroup, MiniBrowserError, MiniBrowserVaultEntry, MiniBrowserVaultOp } from '../../types'
import { useErrorText } from './useErrorText'
import { isSocketConnected, sendLive } from './useMiniBrowserSocket'
import { LABEL_MAX, PASSWORD_MAX, USERNAME_MAX, siteHost, validateSite } from './vaultForm'
import styles from './PasswordsModal.module.css'
import { CredentialValueModal } from './CredentialValueModal'

// A write normally answers within a second; past this the dialog stops
// waiting and says so (the request may still land — the list refreshes).
const RESULT_TIMEOUT_MS = 15_000
const KINDS: CredentialKind[] = ['login', 'api_key', 'secure_note']
const GROUPS: CredentialGroup[] = ['work', 'personal', 'other']
const NOTE_MAX = 16384
const kindOf = (entry: MiniBrowserVaultEntry): CredentialKind => entry.kind ?? 'login'
const groupOf = (entry: MiniBrowserVaultEntry): CredentialGroup => entry.group ?? 'other'
const kindIcon = (kind: CredentialKind) => kind === 'login' ? <Globe size={16} /> : kind === 'api_key' ? <Code2 size={16} /> : <FileText size={16} />

// Keep password managers (1Password, LastPass, Bitwarden, Chrome's own) away
// from this form: these are third-party credentials, not CraftBot's.
const NO_AUTOFILL = {
  autoComplete: 'off',
  'data-1p-ignore': '',
  'data-lpignore': 'true',
  'data-bwignore': '',
  'data-form-type': 'other',
} as const

type FormMode = { kind: 'add' } | { kind: 'edit'; entry: MiniBrowserVaultEntry }

interface Pending {
  op: MiniBrowserVaultOp
  /** The entry being deleted. */
  entryId?: string
}

interface PasswordsModalProps {
  isOpen: boolean
  onClose(): void
}

interface PasswordsPanelProps {
  isOpen?: boolean
  /** Omit to show the manager inline in Settings. */
  onClose?(): void
}

/** Accepts epoch seconds/ms or an ISO string; null when unusable. */
function toDate(value: string | number | null): Date | null {
  if (value === null) return null
  const date = typeof value === 'number' ? new Date(value < 1e12 ? value * 1000 : value) : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/**
 * The resource cache holds metadata only. Typed values live in the editor
 * until save or close. API key/note reveal is confined to a temporary child
 * dialog; login passwords remain available only to browser autofill.
 */
export function PasswordsPanel({ isOpen = true, onClose }: PasswordsPanelProps) {
  const { t } = useTranslation(['minibrowser', 'common'])
  const { showToast } = useToast()
  const errorText = useErrorText()
  const idPrefix = useId()

  useResource(isOpen ? RESOURCES.miniBrowserVault : null)
  const loaded = useAppSelector(selectMiniBrowserVaultLoaded)
  const entries = useAppSelector(selectMiniBrowserVaultEntries)
  const status = useAppSelector(selectMiniBrowserVaultStatus)
  const listError = useAppSelector(selectMiniBrowserVaultError)
  const result = useAppSelector(selectMiniBrowserVaultResult)

  // Every opening shows the vault as it is now (it may have recovered, or
  // an agent's sign-in changed "last used"). Coalesces with useResource's
  // own first request.
  useEffect(() => {
    if (isOpen) resourceSync.refresh(RESOURCES.miniBrowserVault)
  }, [isOpen])

  // "Try again" on a vault that couldn't be loaded: busy until the reply.
  const [retrying, setRetrying] = useState(false)
  useEffect(() => {
    setRetrying(false)
  }, [status, listError])
  useEffect(() => {
    if (!retrying) return
    const timer = window.setTimeout(() => setRetrying(false), RESULT_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [retrying])
  const retryList = () => {
    setRetrying(true)
    resourceSync.refresh(RESOURCES.miniBrowserVault)
  }

  const [mode, setMode] = useState<FormMode | null>(null)
  const [site, setSite] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [label, setLabel] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<MiniBrowserVaultEntry | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const [filter, setFilter] = useState('')
  const [kindFilter, setKindFilter] = useState<CredentialKind | 'all'>('all')
  const [groupFilter, setGroupFilter] = useState<CredentialGroup | 'all'>('all')
  const [kind, setKind] = useState<CredentialKind>('login')
  const [group, setGroup] = useState<CredentialGroup>('other')
  const [viewEntry, setViewEntry] = useState<MiniBrowserVaultEntry | null>(null)

  const siteRef = useRef<HTMLInputElement>(null)
  // Results that predate this dialog are not ours.
  const seenResultSeqRef = useRef(result?.seq ?? 0)

  const resetForm = useCallback(() => {
    setMode(null)
    setSite('')
    setUsername('')
    setPassword('')
    setLabel('')
    setShowPassword(false)
    setSubmitted(false)
    setFormError(null)
  }, [])

  // Closing clears every field, the password above all.
  useEffect(() => {
    if (isOpen) return
    resetForm()
    setPending(null)
    setConfirmDelete(null)
    setConfirmReset(false)
    setFilter('')
  }, [isOpen, resetForm])

  useEffect(() => {
    if (!mode) return
    const opener = document.activeElement as HTMLElement | null
    siteRef.current?.focus()
    return () => opener?.focus?.({ preventScroll: true })
  }, [mode, kind])

  useEffect(() => { setViewEntry(null) }, [filter, kindFilter, groupFilter, isOpen])

  // ── Results of our writes ─────────────────────────────────────────────
  useEffect(() => {
    if (!result || result.seq === seenResultSeqRef.current) return
    seenResultSeqRef.current = result.seq
    if (!pending) return
    const { op, entryId } = pending
    setPending(null)
    if (!result.ok) {
      const text = result.error ? errorText(result.error) : null
      setFormError(text ? [text.message || text.title, text.detail].filter(Boolean).join(' — ') : t('minibrowser:passwords.error'))
      return
    }
    // The list is fetched again so it reflects the change right away.
    resourceSync.refresh(RESOURCES.miniBrowserVault)
    if (op === 'add' || op === 'update') {
      resetForm()
      if (op === 'add') {
        setFilter('')
        setKindFilter('all')
        setGroupFilter('all')
      }
      showToast('success', op === 'add' ? t('minibrowser:credentials.saved') : t('minibrowser:credentials.updated'))
    } else if (op === 'delete') {
      // Deleted the login being edited: the form has nothing to edit any more.
      if (mode?.kind === 'edit' && mode.entry.id === entryId) resetForm()
      showToast('success', t('minibrowser:credentials.deleted'))
    } else {
      showToast('success', t('minibrowser:passwords.resetDone'))
    }
  }, [result, pending, mode, errorText, resetForm, showToast, t])

  useEffect(() => {
    if (!pending) return
    const timer = window.setTimeout(() => {
      setPending(null)
      setFormError(t('minibrowser:passwords.timeout'))
      resourceSync.refresh(RESOURCES.miniBrowserVault)
    }, RESULT_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [pending, t])

  /** Sends only while connected: a queued write would keep the password in
   *  the outbox and could replay much later. */
  const sendVault = useCallback((type: string, data: Record<string, unknown>, pendingOp: Pending): void => {
    if (!isSocketConnected() || !sendLive(type, data)) {
      setFormError(t('minibrowser:passwords.notConnected'))
      return
    }
    setFormError(null)
    setPending(pendingOp)
  }, [t])

  // ── Validation ────────────────────────────────────────────────────────
  const editing = mode?.kind === 'edit'
  const isLogin = kind === 'login'
  const isNote = kind === 'secure_note'
  const secretMax = isNote ? NOTE_MAX : PASSWORD_MAX
  const secretPlaceholder = editing
    ? t('minibrowser:credentials.keepValue')
    : t(isNote ? 'minibrowser:credentials.placeholders.note' : isLogin ? 'minibrowser:credentials.placeholders.password' : 'minibrowser:credentials.placeholders.apiKey')
  const siteProblem = isLogin || site.trim() ? validateSite(site) : null
  const usernameProblem = !isLogin ? null : !username.trim()
    ? t('minibrowser:passwords.required')
    : username.length > USERNAME_MAX
      ? t('minibrowser:passwords.tooLong', { max: USERNAME_MAX })
      : null
  const passwordProblem = !editing && !password
    ? t('minibrowser:passwords.required')
    : password.length > secretMax
      ? t('minibrowser:passwords.tooLong', { max: secretMax })
      : null
  const labelProblem = !isLogin && !label.trim() ? t('minibrowser:passwords.required') : label.length > LABEL_MAX ? t('minibrowser:passwords.tooLong', { max: LABEL_MAX }) : null
  const siteMessage = siteProblem === 'required'
    ? t('minibrowser:passwords.required')
    : siteProblem === 'invalid' ? t('minibrowser:passwords.invalidSite') : null
  const invalid = !!(siteMessage || usernameProblem || passwordProblem || labelProblem)

  // Saving a login for an existing site + username replaces its password.
  const replaces = useMemo(() => {
    if (!isLogin || editing || !site.trim() || !username.trim()) return null
    const host = siteHost(site)
    const user = username.trim().toLowerCase()
    return entries.find(entry => kindOf(entry) === 'login' && siteHost(entry.site) === host && entry.username.toLowerCase() === user) ?? null
  }, [isLogin, editing, entries, site, username])

  // Three ways the vault can be other than "readable": unreadable (needs a
  // reset), unavailable for now (a busy file, a missing dependency: retry),
  // or the list request itself failed. None of them is an empty vault, and
  // none can take a save.
  const unreadable = !!status?.unreadable
  const unavailable = loaded && !unreadable && (!!listError || (status !== null && !status.ok))
  const locked = unreadable || unavailable
  const busy = pending !== null
  const listErrorText = (error: MiniBrowserError): string => {
    const text = errorText(error)
    return [text.message || text.title, text.detail].filter(Boolean).join(' — ')
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (invalid || busy || locked) return
    if (mode?.kind === 'edit') {
      const data: Record<string, unknown> = {
        id: mode.entry.id,
        site: isNote ? '' : site.trim(),
        username: isLogin ? username.trim() : '',
        label: label.trim(),
        kind, group,
      }
      if (password) data.password = password
      sendVault('mini_browser_vault_update', data, { op: 'update' })
    } else {
      sendVault(
        'mini_browser_vault_add',
        { site: isNote ? '' : site.trim(), username: isLogin ? username.trim() : '', password, label: label.trim(), kind, group },
        { op: 'add' },
      )
    }
  }

  const startEdit = (entry: MiniBrowserVaultEntry) => {
    setKind(kindOf(entry))
    setGroup(groupOf(entry))
    setViewEntry(null)
    setMode({ kind: 'edit', entry })
    setSite(entry.site)
    setUsername(entry.username)
    setLabel(entry.label)
    setPassword('')
    setShowPassword(false)
    setSubmitted(false)
    setFormError(null)
  }

  const startAdd = () => {
    resetForm()
    setKind(kindFilter === 'all' ? 'login' : kindFilter)
    setGroup(groupFilter === 'all' ? 'other' : groupFilter)
    setMode({ kind: 'add' })
  }

  const doDelete = () => {
    const entry = confirmDelete
    setConfirmDelete(null)
    if (!entry) return
    sendVault('mini_browser_vault_delete', { id: entry.id }, { op: 'delete', entryId: entry.id })
  }

  const doReset = () => {
    setConfirmReset(false)
    sendVault('mini_browser_vault_reset', {}, { op: 'reset' })
  }

  const dirty = !!(site || username || password || label)
  const needle = filter.trim().toLowerCase()
  const titleOf = (entry: MiniBrowserVaultEntry) => entry.label || entry.site
  const visible = entries.filter(entry =>
    (kindFilter === 'all' || kindOf(entry) === kindFilter) &&
    (groupFilter === 'all' || groupOf(entry) === groupFilter) &&
    (!needle || [entry.site, entry.username, entry.label,
      t(`minibrowser:credentials.kinds.${kindOf(entry)}`),
      t(`minibrowser:credentials.groups.${groupOf(entry)}`),
    ].some(value => value.toLowerCase().includes(needle))),
  ).sort((a, b) => titleOf(a).localeCompare(titleOf(b)))

  const fieldId = (name: string) => `${idPrefix}-${name}`
  const showErrors = submitted
  const lastUsed = (entry: MiniBrowserVaultEntry): string => {
    const date = toDate(entry.lastUsedAt)
    return date
      ? t('minibrowser:passwords.lastUsed', { date: formatDate(date, { year: 'numeric', month: 'short', day: 'numeric' }) })
      : t('minibrowser:passwords.neverUsed')
  }
  // The line under the title; a login's site is left out when it is the title.
  const detailOf = (entry: MiniBrowserVaultEntry): string => {
    const entryKind = kindOf(entry)
    if (entryKind !== 'login') return entry.site || t(`minibrowser:credentials.kinds.${entryKind}`)
    return [entry.label ? entry.site : '', entry.username, lastUsed(entry)].filter(Boolean).join(' · ')
  }

  const content = (
    <div className={styles.body}>
      <p className={styles.intro}>{t('minibrowser:credentials.intro')}</p>
      {status?.ok && !locked && <p className={styles.protection}><ShieldCheck size={14} />
        {t(status.protection === 'dpapi' ? 'minibrowser:passwords.protectionDpapi' : 'minibrowser:passwords.protectionFile')}
      </p>}
      {unreadable && <div className={styles.unreadable} role="alert">
        <AlertTriangle size={18} /><div><strong>{t('minibrowser:passwords.unreadableTitle')}</strong>
          <p>{t('minibrowser:passwords.unreadableBody')}</p>
          <Button variant="danger" size="sm" disabled={busy} onClick={() => setConfirmReset(true)}>{t('minibrowser:passwords.reset')}</Button>
        </div>
      </div>}
      {unavailable && <div className={styles.unavailable} role="alert"><AlertCircle size={18} /><div>
        <strong>{t('minibrowser:passwords.unavailableTitle')}</strong>
        <p>{t('minibrowser:passwords.unavailableBody')}</p>
        {listError && <p>{listErrorText(listError)}</p>}
        <Button variant="secondary" size="sm" loading={retrying} disabled={retrying} onClick={retryList}>{t('minibrowser:passwords.retry')}</Button>
      </div></div>}
      <div className={styles.toolbar}>
        <label className={styles.search}>
          <Search size={15} />
          <input type="search" value={filter} onChange={e => setFilter(e.target.value)}
            placeholder={t('minibrowser:credentials.search')} aria-label={t('minibrowser:credentials.search')}
            spellCheck={false} {...NO_AUTOFILL} />
        </label>
        <Button variant="primary" onClick={startAdd} disabled={!loaded || busy || locked}>
          <Plus size={16} /> {t('minibrowser:credentials.add')}
        </Button>
      </div>
      <div className={styles.filters}>
        <div className={styles.categories} role="group" aria-label={t('minibrowser:credentials.type')}>
          {(['all', ...KINDS] as const).map(value => <button key={value} type="button"
            aria-pressed={kindFilter === value} className={`${styles.category} ${kindFilter === value ? styles.categoryActive : ''}`}
            onClick={() => setKindFilter(value)}>
            {value === 'all' ? t('minibrowser:credentials.all') : t(`minibrowser:credentials.kinds.${value}`)}
            <span>{value === 'all' ? entries.length : entries.filter(entry => kindOf(entry) === value).length}</span>
          </button>)}
        </div>
        <select className={styles.groupSelect} value={groupFilter} onChange={e => setGroupFilter(e.target.value as typeof groupFilter)} aria-label={t('minibrowser:credentials.group')}>
          <option value="all">{t('minibrowser:credentials.allGroups')}</option>
          {GROUPS.map(value => <option key={value} value={value}>{t(`minibrowser:credentials.groups.${value}`)}</option>)}
        </select>
      </div>
      <section aria-label={t('minibrowser:credentials.list')}>
        {!loaded ? <div className={styles.loading} role="status"><Loader2 size={16} className={styles.spin} />{t('minibrowser:credentials.loading')}</div>
          : visible.length === 0 ? <div className={styles.emptyState}>
            {entries.length === 0 ? <KeyRound size={28} /> : <Search size={28} />}
            <strong>{t(entries.length === 0 ? 'minibrowser:credentials.empty' : 'minibrowser:credentials.noMatches')}</strong>
            <p>{t(entries.length === 0 ? 'minibrowser:credentials.emptyHint' : 'minibrowser:credentials.searchHint')}</p>
            {entries.length > 0 && <Button variant="ghost" size="sm" onClick={() => { setFilter(''); setKindFilter('all'); setGroupFilter('all') }}>{t('minibrowser:credentials.clearFilters')}</Button>}
          </div> : <ul className={styles.list}>
            {visible.map(entry => <li key={entry.id} className={styles.row}>
              <span className={styles.itemIcon} data-kind={kindOf(entry)}>{kindIcon(kindOf(entry))}</span>
              <div className={styles.rowMain}>
                <div className={styles.rowHeader}>
                  <span className={styles.rowTitle}>{titleOf(entry)}</span>
                  <Badge variant="primary" className={styles.rowBadge}>{t(`minibrowser:credentials.groups.${groupOf(entry)}`)}</Badge>
                </div>
                <span className={styles.rowDetail}>{detailOf(entry)}</span>
              </div>
              <div className={styles.rowActions}>
                {kindOf(entry) !== 'login' && <IconButton size="sm" icon={<Eye />} disabled={busy || locked}
                  onClick={() => setViewEntry(entry)} aria-label={t('minibrowser:credentials.viewNamed', { name: titleOf(entry) })} tooltip={t('minibrowser:credentials.view')} />}
                <IconButton size="sm" icon={<Pencil />} disabled={busy || locked} onClick={() => startEdit(entry)}
                  aria-label={t('minibrowser:credentials.editNamed', { name: titleOf(entry) })} tooltip={t('minibrowser:passwords.edit')} />
                <IconButton size="sm" icon={<Trash2 />} disabled={busy || locked} className={styles.deleteButton} onClick={() => setConfirmDelete(entry)}
                  aria-label={t('minibrowser:credentials.deleteNamed', { name: titleOf(entry) })} tooltip={t('minibrowser:passwords.delete')} />
              </div>
            </li>)}
          </ul>}
      </section>
      {!mode && formError && <div className={styles.errorBox} role="alert"><AlertCircle size={16} />{formError}</div>}
    </div>
  )

  return (
    <>
      {onClose ? <Modal isOpen={isOpen} onClose={onClose} size="md" title={<><KeyRound size={18} /> {t('minibrowser:credentials.title')}</>}
        closeOnEsc={!mode && !viewEntry && !confirmDelete && !confirmReset} closeOnOverlayClick={!mode && !viewEntry && !busy} contentClassName={styles.dialog}>
        <ModalBody>{content}</ModalBody><ModalFooter><Button variant="secondary" onClick={onClose}>{t('common:actions.close')}</Button></ModalFooter>
      </Modal> : content}

      {mode && <Modal isOpen onClose={resetForm} size="md" title={t(editing ? 'minibrowser:credentials.editTitle' : 'minibrowser:credentials.add')}
        closeDisabled={busy} closeOnOverlayClick={!dirty && !busy}>
        <ModalBody>
          <form id={fieldId('form')} className={styles.editorForm} onSubmit={submit} noValidate autoComplete="off">
            <div className={styles.formColumns}>
              <div className={styles.field}><label htmlFor={fieldId('kind')}>{t('minibrowser:credentials.type')}</label>
                <select id={fieldId('kind')} value={kind} disabled={editing || busy} onChange={e => { setKind(e.target.value as CredentialKind); setPassword(''); setSite(''); setUsername(''); setShowPassword(false); setSubmitted(false) }}>
                  {KINDS.map(value => <option key={value} value={value}>{t(`minibrowser:credentials.kinds.${value}`)}</option>)}
                </select>
              </div>
              <div className={styles.field}><label htmlFor={fieldId('group')}>{t('minibrowser:credentials.group')}</label>
                <select id={fieldId('group')} value={group} disabled={busy} onChange={e => setGroup(e.target.value as CredentialGroup)}>
                  {GROUPS.map(value => <option key={value} value={value}>{t(`minibrowser:credentials.groups.${value}`)}</option>)}
                </select>
              </div>
            </div>
            <div className={styles.field}>
              <label htmlFor={fieldId('label')}>{t(isLogin ? 'minibrowser:credentials.optionalName' : 'minibrowser:credentials.name')}</label>
              <input ref={!isLogin ? siteRef : undefined} id={fieldId('label')} value={label} onChange={e => setLabel(e.target.value)} disabled={busy} maxLength={LABEL_MAX + 1}
                placeholder={t(isLogin ? 'minibrowser:passwords.labelPlaceholder' : isNote ? 'minibrowser:credentials.placeholders.noteName' : 'minibrowser:credentials.placeholders.apiKeyName')}
                aria-invalid={showErrors && !!labelProblem} aria-describedby={showErrors && labelProblem ? fieldId('label-error') : undefined} {...NO_AUTOFILL} />
              {showErrors && labelProblem && <span id={fieldId('label-error')} className={styles.fieldError}>{labelProblem}</span>}
            </div>
            {!isNote && <div className={styles.field}>
              <label htmlFor={fieldId('site')}>{t(isLogin ? 'minibrowser:passwords.site' : 'minibrowser:credentials.optionalWebsite')}</label>
              <input ref={isLogin ? siteRef : undefined} id={fieldId('site')} value={site} onChange={e => setSite(e.target.value)} disabled={busy}
                inputMode="url" autoCapitalize="off" autoCorrect="off" spellCheck={false}
                placeholder={t(isLogin ? 'minibrowser:passwords.sitePlaceholder' : 'minibrowser:credentials.placeholders.apiWebsite')}
                aria-invalid={showErrors && !!siteMessage} aria-describedby={showErrors && siteMessage ? fieldId('site-error') : fieldId('site-hint')} {...NO_AUTOFILL} />
              {showErrors && siteMessage ? <span id={fieldId('site-error')} className={styles.fieldError}>{siteMessage}</span>
                : <span id={fieldId('site-hint')} className={styles.fieldHint}>{t(isLogin ? 'minibrowser:passwords.siteHint' : 'minibrowser:credentials.apiWebsiteHint')}</span>}
            </div>}
            {isLogin && <div className={styles.field}>
              <label htmlFor={fieldId('username')}>{t('minibrowser:passwords.username')}</label>
              <input id={fieldId('username')} value={username} onChange={e => setUsername(e.target.value)} disabled={busy} maxLength={USERNAME_MAX + 1}
                placeholder={t('minibrowser:credentials.placeholders.username')} autoCapitalize="off" autoCorrect="off" spellCheck={false} aria-invalid={showErrors && !!usernameProblem}
                aria-describedby={showErrors && usernameProblem ? fieldId('username-error') : undefined} {...NO_AUTOFILL} />
              {showErrors && usernameProblem && <span id={fieldId('username-error')} className={styles.fieldError}>{usernameProblem}</span>}
            </div>}
            <div className={styles.field}>
              <label htmlFor={fieldId('password')}>{t(isNote ? 'minibrowser:credentials.note' : isLogin ? 'minibrowser:passwords.password' : 'minibrowser:credentials.apiKey')}</label>
              <div className={styles.passwordRow}>
                {isNote ? <textarea id={fieldId('password')} value={password} rows={7} onChange={e => setPassword(e.target.value)} disabled={busy}
                  maxLength={secretMax + 1} placeholder={secretPlaceholder} aria-invalid={showErrors && !!passwordProblem}
                  aria-describedby={showErrors && passwordProblem ? fieldId('password-error') : undefined} {...NO_AUTOFILL} />
                  : <><input id={fieldId('password')} type={showPassword ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)}
                    placeholder={secretPlaceholder} disabled={busy} maxLength={secretMax + 1}
                    autoCapitalize="off" autoCorrect="off" spellCheck={false} aria-invalid={showErrors && !!passwordProblem}
                    aria-describedby={showErrors && passwordProblem ? fieldId('password-error') : undefined} {...NO_AUTOFILL} />
                    <IconButton type="button" variant="secondary" icon={showPassword ? <EyeOff /> : <Eye />} disabled={busy} onClick={() => setShowPassword(value => !value)}
                      aria-label={t(showPassword ? 'minibrowser:passwords.hidePassword' : 'minibrowser:passwords.showPassword')} aria-pressed={showPassword} />
                  </>}
              </div>
              {showErrors && passwordProblem && <span id={fieldId('password-error')} className={styles.fieldError}>{passwordProblem}</span>}
            </div>
            {replaces && <p className={styles.replaceNote}>{t('minibrowser:passwords.willReplace', { site: replaces.site, username: replaces.username })}</p>}
            {formError && <div className={styles.errorBox} role="alert"><AlertCircle size={16} />{formError}</div>}
          </form>
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" onClick={resetForm} disabled={busy}>{t('common:actions.cancel')}</Button>
          <Button form={fieldId('form')} type="submit" variant="primary" loading={busy} disabled={busy || locked}>
            {t(editing ? 'minibrowser:passwords.update' : 'minibrowser:credentials.save')}
          </Button>
        </ModalFooter>
      </Modal>}
      {viewEntry && <CredentialValueModal key={viewEntry.id} entry={viewEntry} onClose={() => setViewEntry(null)} />}
      <ConfirmModal isOpen={!!confirmDelete} title={t('minibrowser:credentials.deleteTitle')}
        message={confirmDelete ? t('minibrowser:credentials.deleteMessage', { name: titleOf(confirmDelete) }) : ''}
        confirmText={t('common:actions.delete')} variant="danger" onConfirm={doDelete} onCancel={() => setConfirmDelete(null)} />
      <ConfirmModal isOpen={confirmReset} title={t('minibrowser:passwords.resetTitle')} message={t('minibrowser:passwords.resetMessage')}
        confirmText={t('minibrowser:passwords.reset')} variant="danger" onConfirm={doReset} onCancel={() => setConfirmReset(false)} />
    </>
  )
}

/** The Mini Browser shortcut uses the same manager as Settings. */
export function PasswordsModal(props: PasswordsModalProps) {
  return <PasswordsPanel {...props} />
}
