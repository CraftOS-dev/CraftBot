import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertCircle,
  AlertTriangle,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Pencil,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { Button, ConfirmModal, IconButton, Modal, ModalBody, ModalFooter } from '../../components/ui'
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
import type { MiniBrowserVaultEntry, MiniBrowserVaultOp } from '../../types'
import { useErrorText } from './useErrorText'
import { isSocketConnected, sendLive } from './useMiniBrowserSocket'
import { LABEL_MAX, PASSWORD_MAX, USERNAME_MAX, siteHost, validateSite } from './vaultForm'
import styles from './PasswordsModal.module.css'

// A write normally answers within a second; past this the dialog stops
// waiting and says so (the request may still land — the list refreshes).
const RESULT_TIMEOUT_MS = 15_000
// Show a filter box once the list gets long.
const FILTER_THRESHOLD = 8

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

/** Accepts epoch seconds/ms or an ISO string; null when unusable. */
function toDate(value: string | number | null): Date | null {
  if (value === null) return null
  const date = typeof value === 'number' ? new Date(value < 1e12 ? value * 1000 : value) : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/**
 * Saved logins the agents can use to sign in. The UI never receives a
 * password: the list carries site, username and label only, and a typed
 * password lives in this component just until the backend confirms the save.
 * Unmounting (closing) drops every field.
 */
export function PasswordsModal({ isOpen, onClose }: PasswordsModalProps) {
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

  const [mode, setMode] = useState<FormMode>({ kind: 'add' })
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

  const siteRef = useRef<HTMLInputElement>(null)
  // Results that predate this dialog are not ours.
  const seenResultSeqRef = useRef(result?.seq ?? 0)

  const resetForm = useCallback(() => {
    setMode({ kind: 'add' })
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

  // Start in the first field; give focus back to whatever opened the dialog.
  useEffect(() => {
    if (!isOpen) return
    const opener = document.activeElement as HTMLElement | null
    siteRef.current?.focus()
    return () => opener?.focus?.({ preventScroll: true })
  }, [isOpen])

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
      showToast('success', op === 'add' ? t('minibrowser:passwords.saved') : t('minibrowser:passwords.updated'))
    } else if (op === 'delete') {
      // Deleted the login being edited: the form has nothing to edit any more.
      if (mode.kind === 'edit' && mode.entry.id === entryId) resetForm()
      showToast('success', t('minibrowser:passwords.deleted'))
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
  const editing = mode.kind === 'edit'
  const siteProblem = validateSite(site)
  const usernameProblem = !username.trim()
    ? t('minibrowser:passwords.required')
    : username.length > USERNAME_MAX
      ? t('minibrowser:passwords.tooLong', { max: USERNAME_MAX })
      : null
  const passwordProblem = !editing && !password
    ? t('minibrowser:passwords.required')
    : password.length > PASSWORD_MAX
      ? t('minibrowser:passwords.tooLong', { max: PASSWORD_MAX })
      : null
  const labelProblem = label.length > LABEL_MAX ? t('minibrowser:passwords.tooLong', { max: LABEL_MAX }) : null
  const siteMessage = siteProblem === 'required'
    ? t('minibrowser:passwords.required')
    : siteProblem === 'invalid' ? t('minibrowser:passwords.invalidSite') : null
  const invalid = !!(siteMessage || usernameProblem || passwordProblem || labelProblem)

  // Saving a login for an existing site + username replaces its password.
  const replaces = useMemo(() => {
    if (editing || !site.trim() || !username.trim()) return null
    const host = siteHost(site)
    const user = username.trim().toLowerCase()
    return entries.find(entry => siteHost(entry.site) === host && entry.username.toLowerCase() === user) ?? null
  }, [editing, entries, site, username])

  const unreadable = !!status?.unreadable
  const busy = pending !== null

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (invalid || busy || unreadable) return
    if (mode.kind === 'edit') {
      const data: Record<string, unknown> = {
        id: mode.entry.id,
        site: site.trim(),
        username: username.trim(),
        label: label.trim(),
      }
      if (password) data.password = password
      sendVault('mini_browser_vault_update', data, { op: 'update' })
    } else {
      sendVault(
        'mini_browser_vault_add',
        { site: site.trim(), username: username.trim(), password, label: label.trim() },
        { op: 'add' },
      )
    }
  }

  const startEdit = (entry: MiniBrowserVaultEntry) => {
    setMode({ kind: 'edit', entry })
    setSite(entry.site)
    setUsername(entry.username)
    setLabel(entry.label)
    setPassword('')
    setShowPassword(false)
    setSubmitted(false)
    setFormError(null)
    siteRef.current?.focus()
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
  const visible = needle
    ? entries.filter(entry =>
      [entry.site, entry.username, entry.label].some(value => value.toLowerCase().includes(needle)))
    : entries

  const fieldId = (name: string) => `${idPrefix}-${name}`
  const showErrors = submitted
  const lastUsed = (entry: MiniBrowserVaultEntry): string => {
    const date = toDate(entry.lastUsedAt)
    return date
      ? t('minibrowser:passwords.lastUsed', { date: formatDate(date, { year: 'numeric', month: 'short', day: 'numeric' }) })
      : t('minibrowser:passwords.neverUsed')
  }

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size="md"
        title={<><KeyRound size={18} /> {t('minibrowser:passwords.title')}</>}
        closeOnEsc={!confirmDelete && !confirmReset}
        closeOnOverlayClick={!dirty && !busy}
        contentClassName={styles.dialog}
      >
        <ModalBody className={styles.body}>
          <p className={styles.intro}>{t('minibrowser:passwords.intro')}</p>
          {status && !unreadable && (
            <p className={styles.protection}>
              <ShieldCheck size={14} />
              {status.protection === 'dpapi'
                ? t('minibrowser:passwords.protectionDpapi')
                : t('minibrowser:passwords.protectionFile')}
            </p>
          )}

          {unreadable && (
            <div className={styles.unreadable} role="alert">
              <AlertTriangle size={18} className={styles.unreadableIcon} />
              <div>
                <strong>{t('minibrowser:passwords.unreadableTitle')}</strong>
                <p>{t('minibrowser:passwords.unreadableBody')}</p>
                <Button
                  variant="danger"
                  size="sm"
                  loading={pending?.op === 'reset'}
                  disabled={busy}
                  onClick={() => setConfirmReset(true)}
                >
                  {t('minibrowser:passwords.reset')}
                </Button>
              </div>
            </div>
          )}

          {listError && !unreadable && (
            <div className={styles.errorBox} role="alert">
              <AlertCircle size={16} />
              <span>{errorText(listError).message || errorText(listError).title}</span>
            </div>
          )}

          <section className={styles.listSection} aria-label={t('minibrowser:passwords.listLabel')}>
            <div className={styles.listHeader}>
              <h4 className={styles.sectionTitle}>
                {t('minibrowser:passwords.listLabel')}
                {loaded && entries.length > 0 && (
                  <span className={styles.count}>{t('minibrowser:passwords.count', { count: entries.length })}</span>
                )}
              </h4>
              {entries.length > FILTER_THRESHOLD && (
                <label className={styles.filter}>
                  <Search size={13} />
                  <input
                    type="search"
                    value={filter}
                    onChange={e => setFilter(e.target.value)}
                    placeholder={t('minibrowser:passwords.filter')}
                    aria-label={t('minibrowser:passwords.filter')}
                    spellCheck={false}
                    {...NO_AUTOFILL}
                  />
                </label>
              )}
            </div>

            {!loaded ? (
              <div className={styles.loading} role="status">
                <Loader2 size={16} className={styles.spin} />
                {t('minibrowser:passwords.loading')}
              </div>
            ) : entries.length === 0 ? (
              <p className={styles.empty}>
                {unreadable ? t('minibrowser:passwords.emptyUnreadable') : t('minibrowser:passwords.empty')}
              </p>
            ) : (
              <ul className={styles.list}>
                {visible.map(entry => {
                  const beingEdited = mode.kind === 'edit' && mode.entry.id === entry.id
                  return (
                    <li key={entry.id} className={`${styles.row} ${beingEdited ? styles.rowEditing : ''}`}>
                      <div className={styles.rowMain}>
                        <span className={styles.rowSite}>{entry.site}</span>
                        <span className={styles.rowUser}>{entry.username}</span>
                        <span className={styles.rowMeta}>
                          {entry.label && <span className={styles.rowLabel}>{entry.label}</span>}
                          <span>{lastUsed(entry)}</span>
                        </span>
                      </div>
                      <span className={styles.rowSecret} aria-hidden="true">••••••••</span>
                      <div className={styles.rowActions}>
                        <IconButton
                          type="button"
                          size="sm"
                          icon={<Pencil />}
                          onClick={() => startEdit(entry)}
                          disabled={busy || unreadable}
                          aria-label={t('minibrowser:passwords.editNamed', { site: entry.site, username: entry.username })}
                          tooltip={t('minibrowser:passwords.edit')}
                        />
                        <IconButton
                          type="button"
                          size="sm"
                          icon={<Trash2 />}
                          className={styles.deleteButton}
                          onClick={() => setConfirmDelete(entry)}
                          disabled={busy || unreadable}
                          aria-label={t('minibrowser:passwords.deleteNamed', { site: entry.site, username: entry.username })}
                          tooltip={t('minibrowser:passwords.delete')}
                        />
                      </div>
                    </li>
                  )
                })}
                {visible.length === 0 && <li className={styles.empty}>{t('minibrowser:passwords.noMatches')}</li>}
              </ul>
            )}
          </section>

          <form
            className={styles.form}
            onSubmit={submit}
            noValidate
            autoComplete="off"
            aria-labelledby={fieldId('form-title')}
          >
            <h4 id={fieldId('form-title')} className={styles.sectionTitle}>
              {editing ? t('minibrowser:passwords.editTitle') : t('minibrowser:passwords.addTitle')}
            </h4>

            <div className={styles.field}>
              <label htmlFor={fieldId('site')}>{t('minibrowser:passwords.site')}</label>
              <input
                ref={siteRef}
                id={fieldId('site')}
                type="text"
                value={site}
                onChange={e => setSite(e.target.value)}
                placeholder={t('minibrowser:passwords.sitePlaceholder')}
                inputMode="url"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                disabled={busy || unreadable}
                aria-invalid={showErrors && !!siteMessage}
                aria-describedby={fieldId(showErrors && siteMessage ? 'site-error' : 'site-hint')}
                {...NO_AUTOFILL}
              />
              {showErrors && siteMessage ? (
                <span id={fieldId('site-error')} className={styles.fieldError}>{siteMessage}</span>
              ) : (
                <span id={fieldId('site-hint')} className={styles.fieldHint}>{t('minibrowser:passwords.siteHint')}</span>
              )}
            </div>

            <div className={styles.field}>
              <label htmlFor={fieldId('username')}>{t('minibrowser:passwords.username')}</label>
              <input
                id={fieldId('username')}
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                maxLength={USERNAME_MAX + 1}
                disabled={busy || unreadable}
                aria-invalid={showErrors && !!usernameProblem}
                aria-describedby={showErrors && usernameProblem ? fieldId('username-error') : undefined}
                {...NO_AUTOFILL}
              />
              {showErrors && usernameProblem && (
                <span id={fieldId('username-error')} className={styles.fieldError}>{usernameProblem}</span>
              )}
            </div>

            <div className={styles.field}>
              <label htmlFor={fieldId('password')}>{t('minibrowser:passwords.password')}</label>
              <div className={styles.passwordRow}>
                <input
                  id={fieldId('password')}
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder={editing ? t('minibrowser:passwords.passwordKeep') : undefined}
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  maxLength={PASSWORD_MAX + 1}
                  disabled={busy || unreadable}
                  aria-invalid={showErrors && !!passwordProblem}
                  aria-describedby={showErrors && passwordProblem ? fieldId('password-error') : undefined}
                  {...NO_AUTOFILL}
                />
                <IconButton
                  type="button"
                  size="md"
                  variant="secondary"
                  icon={showPassword ? <EyeOff /> : <Eye />}
                  onClick={() => setShowPassword(shown => !shown)}
                  disabled={busy || unreadable}
                  aria-pressed={showPassword}
                  aria-controls={fieldId('password')}
                  aria-label={showPassword ? t('minibrowser:passwords.hidePassword') : t('minibrowser:passwords.showPassword')}
                  tooltip={showPassword ? t('minibrowser:passwords.hidePassword') : t('minibrowser:passwords.showPassword')}
                />
              </div>
              {showErrors && passwordProblem && (
                <span id={fieldId('password-error')} className={styles.fieldError}>{passwordProblem}</span>
              )}
            </div>

            <div className={styles.field}>
              <label htmlFor={fieldId('label')}>{t('minibrowser:passwords.label')}</label>
              <input
                id={fieldId('label')}
                type="text"
                value={label}
                onChange={e => setLabel(e.target.value)}
                placeholder={t('minibrowser:passwords.labelPlaceholder')}
                maxLength={LABEL_MAX + 1}
                disabled={busy || unreadable}
                aria-invalid={showErrors && !!labelProblem}
                aria-describedby={showErrors && labelProblem ? fieldId('label-error') : undefined}
                {...NO_AUTOFILL}
              />
              {showErrors && labelProblem && (
                <span id={fieldId('label-error')} className={styles.fieldError}>{labelProblem}</span>
              )}
            </div>

            {replaces && (
              <p className={styles.replaceNote}>
                {t('minibrowser:passwords.willReplace', { site: replaces.site, username: replaces.username })}
              </p>
            )}

            {formError && (
              <div className={styles.errorBox} role="alert">
                <AlertCircle size={16} />
                <span>{formError}</span>
              </div>
            )}

            <div className={styles.formActions}>
              {editing && (
                <Button type="button" variant="ghost" onClick={resetForm} disabled={busy}>
                  {t('minibrowser:passwords.cancelEdit')}
                </Button>
              )}
              <Button
                type="submit"
                variant="primary"
                loading={pending?.op === 'add' || pending?.op === 'update'}
                disabled={busy || unreadable}
              >
                {editing ? t('minibrowser:passwords.update') : t('minibrowser:passwords.save')}
              </Button>
            </div>
          </form>
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" onClick={onClose}>
            {t('common:actions.close')}
          </Button>
        </ModalFooter>
      </Modal>

      <ConfirmModal
        isOpen={!!confirmDelete}
        title={t('minibrowser:passwords.deleteTitle')}
        message={confirmDelete
          ? t('minibrowser:passwords.deleteMessage', { site: confirmDelete.site, username: confirmDelete.username })
          : ''}
        confirmText={t('common:actions.delete')}
        variant="danger"
        onConfirm={doDelete}
        onCancel={() => setConfirmDelete(null)}
      />
      <ConfirmModal
        isOpen={confirmReset}
        title={t('minibrowser:passwords.resetTitle')}
        message={t('minibrowser:passwords.resetMessage')}
        confirmText={t('minibrowser:passwords.reset')}
        variant="danger"
        onConfirm={doReset}
        onCancel={() => setConfirmReset(false)}
      />
    </>
  )
}
