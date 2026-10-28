/**
 * Settings > Credentials: the credential vault (logins, API keys, secure
 * notes). Values never sit in the list: an API key or note is revealed on
 * request (v), hides itself after 30 seconds, and can be copied to the
 * clipboard (c) without being shown. Login passwords stay with browser
 * autofill (the backend never reveals them); c copies a login's username.
 * a adds, e edits, d deletes (confirm). Same messages as the browser's
 * Credentials tab (mini_browser_vault_*).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../../state/hooks'
import {
  selectMiniBrowserVaultEntries,
  selectMiniBrowserVaultError,
  selectMiniBrowserVaultLoaded,
  selectMiniBrowserVaultResult,
  selectMiniBrowserVaultStatus,
} from '../../../../../browser/frontend/src/store/selectors/miniBrowser'
import { RESOURCES, resourceSync, useResource } from '../../../../../browser/frontend/src/store/resources'
import { getSocketClient } from '../../../../../browser/frontend/src/store/socket/socketInstance'
import { useErrorText } from '../../../../../browser/frontend/src/components/MiniBrowser/useErrorText'
import {
  LABEL_MAX,
  PASSWORD_MAX,
  USERNAME_MAX,
  siteHost,
  validateSite,
} from '../../../../../browser/frontend/src/components/MiniBrowser/vaultForm'
import type {
  CredentialGroup,
  CredentialKind,
  MiniBrowserError,
  MiniBrowserVaultEntry,
} from '../../../../../browser/frontend/src/types'
import { useTab } from '../tabContext'
import { clampList, listKey, LIST_START } from '../../../ui/list'
import { confirmKey, type PendingConfirm } from '../../../ui/Confirm'
import * as TB from '../../../input/TextBuffer'
import { useTicker } from '../../../ui/useTicker'
import { glyphs, ink } from '../../../theme/theme'
import { truncate, wrap } from '../../../text/width'
import { copyToClipboard } from '../connectClipboard'
import {
  FilterLine,
  filterKey,
  FormView,
  formInit,
  formKey,
  formTyping,
  formValues,
  newRequestId,
  NoticeLine,
  Row,
  str,
  useConnectKeys,
  useHints,
  useInbound,
  useNotice,
  useSpinner,
  useTextFocus,
  type FormField,
  type FormState,
  ConfirmBlock,
} from '../connectKit'

const REVEAL_MS = 30_000
const RESULT_TIMEOUT_MS = 15_000
const NOTE_MAX = 16384
const KINDS: CredentialKind[] = ['login', 'api_key', 'secure_note']
const GROUPS: CredentialGroup[] = ['work', 'personal', 'other']

const kindOf = (entry: MiniBrowserVaultEntry): CredentialKind => entry.kind ?? 'login'
const groupOf = (entry: MiniBrowserVaultEntry): CredentialGroup => entry.group ?? 'other'
const titleOf = (entry: MiniBrowserVaultEntry): string => entry.label || entry.site

function toDate(value: string | number | null): Date | null {
  if (value === null) return null
  const date = typeof value === 'number' ? new Date(value < 1e12 ? value * 1000 : value) : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

interface Editor {
  mode: 'add' | 'edit'
  id: string | null
  form: FormState
  error: string
}

interface Revealed {
  id: string
  value: string
  until: number
}

export function CredentialsTab() {
  const { t, i18n } = useTranslation('settingsConnect')
  const { active, width, height } = useTab()
  const errorText = useErrorText()

  useResource(RESOURCES.miniBrowserVault)
  const loaded = useAppSelector(selectMiniBrowserVaultLoaded)
  const entries = useAppSelector(selectMiniBrowserVaultEntries)
  const status = useAppSelector(selectMiniBrowserVaultStatus)
  const listError = useAppSelector(selectMiniBrowserVaultError)
  const result = useAppSelector(selectMiniBrowserVaultResult)

  const [list, setList] = useState(LIST_START)
  const [filter, setFilter] = useState<TB.Buffer>(TB.EMPTY)
  const [filtering, setFiltering] = useState(false)
  const [kindFilter, setKindFilter] = useState<CredentialKind | 'all'>('all')
  const [editor, setEditor] = useState<Editor | null>(null)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [pending, setPending] = useState<{ op: string } | null>(null)
  const [revealed, setRevealed] = useState<Revealed | null>(null)
  const [waitingReveal, setWaitingReveal] = useState<string | null>(null)
  const [notice, showNotice] = useNotice()
  // token -> what to do with the value when it arrives.
  const reveals = useRef(new Map<string, { id: string; purpose: 'show' | 'copy' }>())
  const seenSeq = useRef(result?.seq ?? 0)

  // Every opening shows the vault as it is now.
  useEffect(() => {
    resourceSync.refresh(RESOURCES.miniBrowserVault)
  }, [])

  const hide = () => {
    setRevealed(null)
    setWaitingReveal(null)
    reveals.current.clear()
  }

  // A revealed value hides itself after 30 s, when the tab loses focus, and when the connection drops.
  useTicker(1000, revealed !== null)
  useEffect(() => {
    if (!revealed) return
    const timer = setTimeout(() => setRevealed(null), Math.max(0, revealed.until - Date.now()))
    return () => clearTimeout(timer)
  }, [revealed])
  useEffect(() => {
    if (!active) hide()
  }, [active])
  useEffect(() => getSocketClient().onClose(() => hide()), [])
  useEffect(() => {
    if (!waitingReveal) return
    const timer = setTimeout(() => {
      reveals.current.clear()
      setWaitingReveal(null)
      showNotice(t('credentials.revealFailed'), 'error')
    }, RESULT_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [waitingReveal])

  const describe = (error: MiniBrowserError | null): string => {
    if (!error) return t('credentials.failed')
    const text = errorText(error)
    return [text.message || text.title, text.detail].filter(Boolean).join(': ')
  }

  // ── Results of our writes ──
  useEffect(() => {
    if (!result || result.seq === seenSeq.current) return
    seenSeq.current = result.seq
    if (!pending) return
    const op = pending.op
    setPending(null)
    if (!result.ok) {
      const message = describe(result.error)
      if (editor) setEditor({ ...editor, error: message })
      else showNotice(message, 'error')
      return
    }
    resourceSync.refresh(RESOURCES.miniBrowserVault)
    if (op === 'add' || op === 'update') {
      setEditor(null)
      showNotice(op === 'add' ? t('credentials.saved') : t('credentials.updated'), 'success')
    } else if (op === 'delete') showNotice(t('credentials.deleted'), 'success')
    else showNotice(t('credentials.resetDone'), 'success')
  }, [result])
  useEffect(() => {
    if (!pending) return
    const timer = setTimeout(() => {
      setPending(null)
      showNotice(t('credentials.timeout'), 'error')
      resourceSync.refresh(RESOURCES.miniBrowserVault)
    }, RESULT_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [pending])

  useInbound(['mini_browser_vault_value', 'mini_browser_vault_result'], (type, d) => {
    if (type === 'mini_browser_vault_value') {
      const request = reveals.current.get(str(d.token))
      if (!request || str(d.id) !== request.id) return
      reveals.current.delete(str(d.token))
      setWaitingReveal(null)
      if (typeof d.value !== 'string') {
        showNotice(t('credentials.revealFailed'), 'error')
        return
      }
      const value = d.value
      if (request.purpose === 'show') setRevealed({ id: request.id, value, until: Date.now() + REVEAL_MS })
      else
        void copyToClipboard(value).then(copied =>
          showNotice(copied.ok ? t('credentials.copied') : t('credentials.copyFailed'), copied.ok ? 'success' : 'error'),
        )
    } else if (str(d.op) === 'reveal' && d.ok === false && reveals.current.size > 0) {
      reveals.current.clear()
      setWaitingReveal(null)
      showNotice(describe((d.error as MiniBrowserError) ?? null), 'error')
    }
  })

  // ── List ──
  const needle = filter.text.trim().toLowerCase()
  const kindLabel = (kind: CredentialKind) => t(`credentials.kinds.${kind}`)
  const groupLabel = (group: CredentialGroup) => t(`credentials.groups.${group}`)
  const items = entries
    .filter(
      entry =>
        (kindFilter === 'all' || kindOf(entry) === kindFilter) &&
        (!needle ||
          [entry.site, entry.username, entry.label, kindLabel(kindOf(entry)), groupLabel(groupOf(entry))].some(v => v.toLowerCase().includes(needle))),
    )
    .slice()
    .sort((a, b) => titleOf(a).localeCompare(titleOf(b)))
  const listHeight = Math.max(3, height - 6)
  const view = clampList(list, items.length, listHeight)
  const selected = items[view.index]

  // A value belongs to the entry it was revealed for.
  useEffect(() => {
    if (revealed && revealed.id !== selected?.id) setRevealed(null)
  }, [selected?.id])

  const unreadable = !!status?.unreadable
  const unavailable = loaded && !unreadable && (!!listError || (status !== null && !status.ok))
  const locked = unreadable || unavailable
  const busy = pending !== null

  // ── Editor ──
  const editorKind: CredentialKind = editor ? ((formValues(editor.form).kind as CredentialKind) || 'login') : 'login'
  const editing = editor?.mode === 'edit'
  const editorFields: FormField[] = editor
    ? [
        { kind: 'select', key: 'kind', label: t('credentials.type'), options: KINDS.map(k => ({ value: k, label: kindLabel(k) })), locked: editing },
        { kind: 'select', key: 'group', label: t('credentials.group'), options: GROUPS.map(gr => ({ value: gr, label: groupLabel(gr) })) },
        {
          kind: 'text',
          key: 'label',
          label: editorKind === 'login' ? t('credentials.nameOptional') : t('credentials.name'),
          placeholder: editorKind === 'login' ? t('credentials.labelPlaceholder') : editorKind === 'api_key' ? t('credentials.apiKeyNamePlaceholder') : t('credentials.noteNamePlaceholder'),
        },
        ...(editorKind !== 'secure_note'
          ? [
              {
                kind: 'text' as const,
                key: 'site',
                label: editorKind === 'login' ? t('credentials.site') : t('credentials.websiteOptional'),
                placeholder: editorKind === 'login' ? 'example.com' : 'api.example.com',
                hint: editorKind === 'login' ? t('credentials.siteHint') : t('credentials.apiSiteHint'),
              },
            ]
          : []),
        ...(editorKind === 'login'
          ? [{ kind: 'text' as const, key: 'username', label: t('credentials.username'), placeholder: 'you@example.com' }]
          : []),
        {
          kind: 'text',
          key: 'secret',
          label: editorKind === 'login' ? t('credentials.password') : editorKind === 'api_key' ? t('credentials.apiKey') : t('credentials.note'),
          masked: true,
          placeholder: editing ? t('credentials.keepValue') : '',
          hint: editorKind === 'secure_note' ? t('credentials.noteHint') : undefined,
        },
      ]
    : []
  const editorForm: FormState | null = editor ? { ...editor.form, index: Math.min(editor.form.index, editorFields.length - 1) } : null

  useTextFocus(active && (filtering || (editorForm !== null && formTyping(editorForm, editorFields))))
  const spinner = useSpinner(busy || waitingReveal !== null)

  const values = editor ? formValues(editor.form) : {}
  const replaces = useMemo(() => {
    if (!editor || editing || editorKind !== 'login') return null
    const site = String(values.site ?? '').trim()
    const user = String(values.username ?? '').trim().toLowerCase()
    if (!site || !user) return null
    const host = siteHost(site)
    return entries.find(e => kindOf(e) === 'login' && siteHost(e.site) === host && e.username.toLowerCase() === user) ?? null
  }, [editor, editing, editorKind, values.site, values.username, entries])

  const startAdd = () => {
    const kind = kindFilter === 'all' ? 'login' : kindFilter
    setEditor({ mode: 'add', id: null, form: formInit(editorFieldsFor(), { kind, group: 'other' }), error: '' })
  }
  // Every key the editor can show, so switching the type keeps what was typed.
  const editorFieldsFor = (): FormField[] => [
    { kind: 'select', key: 'kind', label: '', options: KINDS.map(k => ({ value: k, label: k })) },
    { kind: 'select', key: 'group', label: '', options: GROUPS.map(gr => ({ value: gr, label: gr })) },
    { kind: 'text', key: 'label', label: '' },
    { kind: 'text', key: 'site', label: '' },
    { kind: 'text', key: 'username', label: '' },
    { kind: 'text', key: 'secret', label: '' },
  ]
  const startEdit = (entry: MiniBrowserVaultEntry) => {
    hide()
    setEditor({
      mode: 'edit',
      id: entry.id,
      form: formInit(editorFieldsFor(), {
        kind: kindOf(entry),
        group: groupOf(entry),
        label: entry.label,
        site: entry.site,
        username: entry.username,
        secret: '',
      }),
      error: '',
    })
  }

  /** Sends only while connected: a queued write would keep the secret in the outbox. */
  const sendVault = (type: string, data: Record<string, unknown>, op: string): boolean => {
    const client = getSocketClient()
    if (!client.isConnected) {
      showNotice(t('credentials.notConnected'), 'error')
      return false
    }
    client.send(type, data)
    setPending({ op })
    return true
  }

  const submit = (form: FormState) => {
    if (!editor || busy) return
    if (locked) {
      setEditor({ ...editor, form, error: t('credentials.lockedNoSave') })
      return
    }
    const v = formValues(form)
    const kind = (v.kind as CredentialKind) || 'login'
    const isLogin = kind === 'login'
    const isNote = kind === 'secure_note'
    const site = isNote ? '' : String(v.site ?? '').trim()
    const username = isLogin ? String(v.username ?? '').trim() : ''
    const label = String(v.label ?? '').trim()
    const secret = String(v.secret ?? '')
    const max = isNote ? NOTE_MAX : PASSWORD_MAX
    const siteProblem = isLogin || site ? validateSite(site) : null
    const problem =
      siteProblem === 'required'
        ? t('credentials.siteRequired')
        : siteProblem === 'invalid'
          ? t('credentials.siteInvalid')
          : isLogin && !username
            ? t('credentials.usernameRequired')
            : username.length > USERNAME_MAX
              ? t('credentials.tooLong', { field: t('credentials.username'), max: USERNAME_MAX })
              : !editing && !secret
                ? t('credentials.secretRequired')
                : secret.length > max
                  ? t('credentials.tooLong', { field: t('credentials.secret'), max })
                  : !isLogin && !label
                    ? t('credentials.nameRequired')
                    : label.length > LABEL_MAX
                      ? t('credentials.tooLong', { field: t('credentials.name'), max: LABEL_MAX })
                      : null
    if (problem) {
      setEditor({ ...editor, form, error: problem })
      return
    }
    const group = (v.group as CredentialGroup) || 'other'
    setEditor({ ...editor, form, error: '' })
    if (editing && editor.id) {
      const data: Record<string, unknown> = { id: editor.id, site, username, label, kind, group }
      if (secret) data.password = secret
      sendVault('mini_browser_vault_update', data, 'update')
    } else {
      sendVault('mini_browser_vault_add', { site, username, password: secret, label, kind, group }, 'add')
    }
  }

  const reveal = (entry: MiniBrowserVaultEntry, purpose: 'show' | 'copy') => {
    const client = getSocketClient()
    if (!client.isConnected) {
      showNotice(t('credentials.notConnected'), 'error')
      return
    }
    const token = newRequestId()
    reveals.current.set(token, { id: entry.id, purpose })
    setWaitingReveal(entry.id)
    client.send('mini_browser_vault_reveal', { id: entry.id, token })
  }

  useConnectKeys((input, key) => {
    if (confirmKey(confirm, input, key, () => setConfirm(null))) return true
    if (editor && editorForm) {
      if (key.escape) {
        if (!busy) setEditor(null)
        return true
      }
      if (busy) return true
      const out = formKey(editorForm, editorFields, input, key)
      if (out?.submit) submit(out.state)
      else if (out) setEditor({ ...editor, form: out.state, error: '' })
      return true
    }
    if (filtering && (key.upArrow || key.downArrow)) {
      const moved = listKey(view, '', key, items.length, listHeight)
      if (moved) setList(moved)
      return true
    }
    const filtered = filterKey(filtering, filter, input, key)
    if (filtered) {
      setFiltering(filtered.filtering)
      setFilter(filtered.buffer)
      if (filtered.changed) setList(LIST_START)
      return true
    }
    const moved = listKey(view, input, key, items.length, listHeight)
    if (moved) {
      setList(moved)
      return true
    }
    if (input === '/') {
      setFiltering(true)
      return true
    }
    if (input === 't') {
      const order: (CredentialKind | 'all')[] = ['all', ...KINDS]
      setKindFilter(order[(order.indexOf(kindFilter) + 1) % order.length])
      setList(LIST_START)
      return true
    }
    if (input === 'r') {
      resourceSync.refresh(RESOURCES.miniBrowserVault)
      showNotice(t('credentials.refreshing'))
      return true
    }
    if (input === 'R' && unreadable) {
      setConfirm({ message: t('credentials.confirmReset'), onConfirm: () => void sendVault('mini_browser_vault_reset', {}, 'reset') })
      return true
    }
    if (input === 'a') {
      if (!loaded || busy || locked) showNotice(locked ? t('credentials.lockedNoSave') : t('common.loading'))
      else startAdd()
      return true
    }
    if (!selected) return false
    const secretKind = kindOf(selected) !== 'login'
    if (input === 'v' || input === ' ') {
      if (!secretKind) showNotice(t('credentials.loginNoReveal'))
      else if (revealed?.id === selected.id) setRevealed(null)
      else if (!locked) reveal(selected, 'show')
      return true
    }
    if (input === 'c') {
      if (!secretKind) {
        void copyToClipboard(selected.username).then(copied =>
          showNotice(copied.ok ? t('credentials.usernameCopied') : t('credentials.copyFailed'), copied.ok ? 'success' : 'error'),
        )
      } else if (revealed?.id === selected.id) {
        void copyToClipboard(revealed.value).then(copied =>
          showNotice(copied.ok ? t('credentials.copied') : t('credentials.copyFailed'), copied.ok ? 'success' : 'error'),
        )
      } else if (!locked) reveal(selected, 'copy')
      return true
    }
    if (input === 'e' || key.return) {
      if (busy || locked) showNotice(t('credentials.lockedNoSave'))
      else startEdit(selected)
      return true
    }
    if (input === 'd') {
      if (busy || locked) return true
      const entry = selected
      setConfirm({
        message: t('credentials.confirmDelete', { name: titleOf(entry) }),
        onConfirm: () => {
          if (revealed?.id === entry.id) setRevealed(null)
          sendVault('mini_browser_vault_delete', { id: entry.id }, 'delete')
        },
      })
      return true
    }
    return false
  })

  useHints(
    editor
      ? [
          { keys: 'Tab', label: t('hint.nextField') },
          { keys: '←/→', label: t('credentials.hintChoose') },
          { keys: 'Enter', label: t('hint.save') },
          { keys: 'Esc', label: t('hint.cancel') },
        ]
      : [
          { keys: 'v', label: t('credentials.hintReveal') },
          { keys: 'c', label: t('credentials.hintCopy') },
          { keys: 'a', label: t('hint.add') },
          { keys: 'e', label: t('hint.edit') },
          { keys: 'd', label: t('hint.delete') },
          { keys: 't', label: t('credentials.hintType') },
          { keys: '/', label: t('hint.filter') },
          ...(unreadable ? [{ keys: 'R', label: t('credentials.hintReset') }] : []),
        ],
  )

  const g = glyphs()
  if (editor && editorForm) {
    return (
      <Box flexDirection="column">
        <Text bold color={ink.brand}>{truncate(editing ? t('credentials.editTitle') : t('credentials.addTitle'), width - 1)}</Text>
        <Text> </Text>
        <FormView fields={editorFields} state={editorForm} width={width} focused={active && !busy} />
        <Text> </Text>
        {replaces ? (
          wrap(t('credentials.willReplace', { username: replaces.username, site: replaces.site }), width - 1).map((line, i) => (
            <Text key={i} color={ink.warn}>{line}</Text>
          ))
        ) : null}
        {busy ? <Text color={ink.muted}>{`${spinner} ${t('common.saving')}`}</Text> : null}
        {editor.error ? wrap(editor.error, width - 1).slice(0, 2).map((line, i) => <Text key={i} color={ink.error}>{line}</Text>) : null}
      </Box>
    )
  }

  const protection = status?.ok && !locked
    ? status.protection === 'dpapi'
      ? t('credentials.protectionDpapi')
      : t('credentials.protectionFile')
    : ''
  const summary = [
    t('credentials.count', { count: entries.length }),
    kindFilter === 'all' ? '' : kindLabel(kindFilter),
    protection,
  ]
    .filter(Boolean)
    .join(' · ')

  const lastUsed = (entry: MiniBrowserVaultEntry): string => {
    const date = toDate(entry.lastUsedAt)
    return date
      ? t('credentials.lastUsed', { date: date.toLocaleDateString(i18n.language, { year: 'numeric', month: 'short', day: 'numeric' }) })
      : t('credentials.neverUsed')
  }

  let valueLine = ''
  let valueColor: string | undefined = ink.muted
  if (selected) {
    if (kindOf(selected) === 'login') valueLine = t('credentials.loginValue')
    else if (revealed?.id === selected.id) {
      const left = Math.max(0, Math.ceil((revealed.until - Date.now()) / 1000))
      valueLine = `${revealed.value.replace(/\s*\n\s*/g, ' ')}  (${t('credentials.hidesIn', { seconds: left })})`
      valueColor = undefined
    } else if (waitingReveal === selected.id) valueLine = `${spinner} ${t('credentials.revealing')}`
    else valueLine = `${'•'.repeat(12)}  ${t('credentials.hiddenValue')}`
  }

  return (
    <Box flexDirection="column">
      <FilterLine
        buffer={filter}
        typing={filtering}
        width={width}
        placeholder={t('credentials.filterPlaceholder')}
        idle={loaded ? summary : t('common.loading')}
      />
      {unreadable ? (
        wrap(t('credentials.unreadable'), width - 1).slice(0, 2).map((line, i) => <Text key={i} color={ink.warn}>{line}</Text>)
      ) : unavailable ? (
        wrap(`${t('credentials.unavailable')}${listError ? ` ${describe(listError)}` : ''}`, width - 1).slice(0, 2).map((line, i) => (
          <Text key={i} color={ink.warn}>{line}</Text>
        ))
      ) : null}
      {loaded && items.length === 0 && !locked ? (
        <Text color={ink.muted}>{truncate(entries.length === 0 ? t('credentials.empty') : t('credentials.noMatch'), width - 1)}</Text>
      ) : null}
      {items.slice(view.top, view.top + listHeight).map((entry, i) => {
        const index = view.top + i
        const kind = kindOf(entry)
        return (
          <Row
            key={entry.id}
            selected={active && index === view.index}
            mark={g.bullet}
            markColor={ink.muted}
            label={titleOf(entry)}
            aside={`${kindLabel(kind)} · ${groupLabel(groupOf(entry))}`}
            width={width}
          />
        )
      })}
      {selected ? (
        <Box flexDirection="column" marginTop={1}>
          <Text color={ink.muted}>
            {truncate(
              kindOf(selected) === 'login'
                ? [selected.label ? selected.site : '', selected.username, lastUsed(selected)].filter(Boolean).join(' · ')
                : selected.site || kindLabel(kindOf(selected)),
              width - 1,
            )}
          </Text>
          <Text color={valueColor}>{truncate(valueLine, width - 1)}</Text>
        </Box>
      ) : null}
      {confirm ? <ConfirmBlock pending={confirm} width={width} hint={t('common.confirmHint')} /> : <NoticeLine notice={notice} width={width} />}
    </Box>
  )
}
