import { useEffect, useRef, useState } from 'react'
import { Plus, Trash2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import type { MCPServerConfig } from '../../store/slices/mcpSettingsSlice'

/**
 * Add or edit one MCP server with a form instead of raw JSON.
 *
 * Secrets are write-only: the backend never sends env or header values, so
 * rows that already have a value start empty and say so. A row left empty
 * is sent as `value: null`, which keeps the stored value; typing replaces
 * it; removing the row deletes it. Validation is the backend's (the same
 * rules as mcp_config.json); its message is shown here as-is.
 */

type Transport = 'stdio' | 'http' | 'sse' | 'websocket'
const TRANSPORTS: Transport[] = ['http', 'stdio', 'sse', 'websocket']
const URL_HIDDEN_MARK = '(credentials/query hidden)'

interface Row {
  id: number
  name: string
  value: string
  /** A value is stored on the backend; empty input keeps it. */
  stored: boolean
  uses?: string[]
}

interface Props {
  mode: 'create' | 'edit'
  server?: MCPServerConfig | null
  onClose: () => void
}

let nextRowId = 1
const row = (name = '', stored = false, uses?: string[]): Row => ({
  id: nextRowId++,
  name,
  value: '',
  stored,
  uses,
})

/** The first name used by two rows, or null. */
const duplicateName = (rows: Row[], caseInsensitive: boolean): string | null => {
  const seen = new Set<string>()
  for (const r of rows) {
    const name = r.name.trim()
    if (!name) continue
    const key = caseInsensitive ? name.toLowerCase() : name
    if (seen.has(key)) return name
    seen.add(key)
  }
  return null
}

export function MCPServerEditor({ mode, server, onClose }: Props) {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage } = useSettingsWebSocket()
  const { showToast } = useToast()

  const initialUrl = server?.url && !server.url.includes(URL_HIDDEN_MARK) ? server.url : ''
  const [name, setName] = useState(server?.name ?? '')
  const [description, setDescription] = useState(server?.description ?? '')
  const [transport, setTransport] = useState<Transport>(
    (TRANSPORTS as string[]).includes(server?.transport ?? '')
      ? (server!.transport as Transport)
      : mode === 'create' ? 'http' : 'stdio',
  )
  const [url, setUrl] = useState(initialUrl)
  const [command, setCommand] = useState(server?.command ?? '')
  // Write-only like env: saved arguments are kept unless replaced.
  const [args, setArgs] = useState('')
  const savedArgs = server?.args_count ?? 0
  const [timeout, setTimeoutValue] = useState(server?.timeout != null ? String(server.timeout) : '')
  const [headers, setHeaders] = useState<Row[]>(
    () => (server?.headers ?? []).map(h => row(h.name, true, h.uses)),
  )
  const [env, setEnv] = useState<Row[]>(
    () => Object.entries(server?.env ?? {}).map(([key, isSet]) => row(key, isSet)),
  )
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const savingName = useRef('')

  useEffect(() => onMessage('mcp_save_server', (data: unknown) => {
    const d = data as { success: boolean; message?: string; name?: string }
    if (d.name !== savingName.current) return
    setSaving(false)
    if (d.success) {
      showToast('success', d.message || t('settings:mcp.toast.configSaved'))
      onClose()
    } else {
      setError(d.message || t('settings:mcp.toast.configFailed'))
    }
  }), [onMessage, showToast, onClose, t])

  const isUrlTransport = transport !== 'stdio'
  const keptHeaders = transport !== 'http' ? headers.filter(r => r.stored).length : 0
  const urlKept = mode === 'edit' && isUrlTransport && !url && !!server?.url

  const update = (setter: typeof setHeaders, id: number, patch: Partial<Row>) =>
    setter(rows => rows.map(r => (r.id === id ? { ...r, ...patch } : r)))

  const submit = () => {
    setError('')
    const trimmed = name.trim()
    if (!trimmed) {
      setError(t('settings:mcp.editor.nameRequired'))
      return
    }
    if (isUrlTransport && !url.trim() && !urlKept) {
      setError(t('settings:mcp.editor.urlRequired'))
      return
    }
    // A second row for a key would replace the first one's (stored) value.
    const duplicate =
      duplicateName(env, false) ?? (transport === 'http' ? duplicateName(headers, true) : null)
    if (duplicate) {
      setError(t('settings:mcp.editor.duplicate', { name: duplicate }))
      return
    }
    const form: Record<string, unknown> = {
      name: trimmed,
      description,
      transport,
      env: env
        .filter(r => r.name.trim())
        .map(r => ({ key: r.name.trim(), value: r.stored && r.value === '' ? null : r.value })),
    }
    if (mode === 'create') form.enabled = true
    if (isUrlTransport) {
      form.url = url.trim() ? url.trim() : null // null keeps the stored URL
    } else {
      form.command = command.trim()
      const typed = args.split('\n').map(a => a.trim()).filter(Boolean)
      form.args = typed.length === 0 && savedArgs > 0 ? null : typed // null keeps them
    }
    if (transport === 'http') {
      form.timeout = timeout.trim() === '' ? null : Number(timeout)
      form.headers = headers
        .filter(r => r.name.trim())
        .map(r => ({ name: r.name.trim(), value: r.stored && r.value === '' ? null : r.value }))
    }
    savingName.current = trimmed
    setSaving(true)
    send('mcp_save_server', { server: form, create: mode === 'create' })
  }

  const renderRows = (
    rows: Row[],
    setter: typeof setHeaders,
    nameLabel: string,
    valueLabel: string,
    addLabel: string,
  ) => (
    <>
      {rows.map(r => (
        <div key={r.id} className={styles.mcpKvRow}>
          <input
            type="text"
            aria-label={nameLabel}
            placeholder={nameLabel}
            value={r.name}
            disabled={r.stored}
            onChange={e => update(setter, r.id, { name: e.target.value })}
          />
          <input
            type="password"
            autoComplete="off"
            aria-label={valueLabel}
            placeholder={r.stored ? t('settings:mcp.editor.keepValue') : valueLabel}
            value={r.value}
            onChange={e => update(setter, r.id, { value: e.target.value })}
          />
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 size={14} />}
            title={t('settings:mcp.remove')}
            onClick={() => setter(list => list.filter(x => x.id !== r.id))}
          />
          {r.uses && r.uses.length > 0 && (
            <span className={styles.labelHint}>
              {t('settings:mcp.editor.uses', { keys: r.uses.join(', ') })}
            </span>
          )}
        </div>
      ))}
      <Button
        variant="secondary"
        size="sm"
        icon={<Plus size={14} />}
        onClick={() => setter(list => [...list, row()])}
      >
        {addLabel}
      </Button>
    </>
  )

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3>
            {mode === 'create'
              ? t('settings:mcp.editor.createTitle')
              : t('settings:mcp.editor.editTitle', { name: server?.name })}
          </h3>
          <button className={styles.modalClose} onClick={onClose} aria-label={t('common:actions.cancel')}>
            <X size={18} />
          </button>
        </div>
        <div className={styles.modalBody}>
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label htmlFor="mcp-name">{t('settings:mcp.editor.name')}</label>
              <input
                id="mcp-name"
                type="text"
                value={name}
                disabled={mode === 'edit'}
                onChange={e => setName(e.target.value)}
              />
            </div>
            <div className={styles.formGroup}>
              <label htmlFor="mcp-transport">{t('settings:mcp.editor.transport')}</label>
              <select
                id="mcp-transport"
                value={transport}
                onChange={e => setTransport(e.target.value as Transport)}
              >
                {TRANSPORTS.map(value => (
                  <option key={value} value={value}>
                    {t(`settings:mcp.editor.transports.${value}`)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="mcp-description">{t('settings:mcp.editor.description')}</label>
            <input
              id="mcp-description"
              type="text"
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
          </div>

          {isUrlTransport ? (
            <div className={styles.formGroup}>
              <label htmlFor="mcp-url">{t('settings:mcp.editor.url')}</label>
              <input
                id="mcp-url"
                type="text"
                value={url}
                placeholder={urlKept ? server?.url ?? '' : 'https://example.com/mcp'}
                onChange={e => setUrl(e.target.value)}
              />
              {urlKept && <span className={styles.labelHint}>{t('settings:mcp.editor.urlKept')}</span>}
            </div>
          ) : (
            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label htmlFor="mcp-command">{t('settings:mcp.editor.command')}</label>
                <input
                  id="mcp-command"
                  type="text"
                  value={command}
                  placeholder="npx"
                  onChange={e => setCommand(e.target.value)}
                />
              </div>
              <div className={styles.formGroup}>
                <label htmlFor="mcp-args">{t('settings:mcp.editor.args')}</label>
                <textarea
                  id="mcp-args"
                  rows={3}
                  value={args}
                  placeholder={savedArgs > 0 ? t('settings:mcp.editor.argsKept', { count: savedArgs }) : ''}
                  onChange={e => setArgs(e.target.value)}
                />
              </div>
            </div>
          )}

          {transport === 'http' && (
            <>
              <div className={styles.formGroup}>
                <label htmlFor="mcp-timeout">{t('settings:mcp.editor.timeout')}</label>
                <input
                  id="mcp-timeout"
                  type="number"
                  min={1}
                  max={300}
                  value={timeout}
                  placeholder="30"
                  onChange={e => setTimeoutValue(e.target.value)}
                />
              </div>
              <div className={styles.formGroup}>
                <label>{t('settings:mcp.editor.headers')}</label>
                <span className={styles.labelHint}>{t('settings:mcp.editor.headersHint')}</span>
                {renderRows(
                  headers,
                  setHeaders,
                  t('settings:mcp.editor.headerName'),
                  t('settings:mcp.editor.headerValue'),
                  t('settings:mcp.editor.addHeader'),
                )}
              </div>
            </>
          )}

          {keptHeaders > 0 && (
            <span className={styles.labelHint}>
              {t('settings:mcp.editor.headersKept', { count: keptHeaders })}
            </span>
          )}

          <div className={styles.formGroup}>
            <label>{t('settings:mcp.editor.env')}</label>
            <span className={styles.labelHint}>{t('settings:mcp.editor.envHint')}</span>
            {renderRows(
              env,
              setEnv,
              t('settings:mcp.editor.envKey'),
              t('settings:mcp.editor.envValue'),
              t('settings:mcp.editor.addEnv'),
            )}
          </div>

          {error && <div className={styles.errorText} role="alert">{error}</div>}
        </div>
        <div className={styles.modalFooter}>
          <Button variant="secondary" onClick={onClose}>
            {t('common:actions.cancel')}
          </Button>
          <Button variant="primary" onClick={submit} disabled={saving}>
            {saving ? t('common:status.saving') : t('common:actions.save')}
          </Button>
        </div>
      </div>
    </div>
  )
}
