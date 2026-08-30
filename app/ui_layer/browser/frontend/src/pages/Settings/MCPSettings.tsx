import { useState, useEffect } from 'react'
import {
  Loader2,
  Plus,
  Edit2,
  Trash2,
  RotateCcw,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button, Badge, ConfirmModal } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { useConfirmModal } from '../../hooks'
import { formatNumber, localeCompare } from '../../i18n/format'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  setLoading as setMcpLoading,
  setEnabled as setMcpEnabled,
  removeServer as removeMcpServer,
  type MCPServerConfig,
} from '../../store/slices/mcpSettingsSlice'
import {
  selectMcpServers,
  selectMcpIsLoading,
  selectMcpHasLoaded,
} from '../../store/selectors/mcpSettings'

interface MCPItem {
  name: string
  description: string
  enabled: boolean
  transport?: string
  action_set?: string
  env?: Record<string, string>
  needsConfig?: boolean
}

export function MCPSettings() {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const { showToast } = useToast()
  const dispatch = useAppDispatch()

  // Slice-backed: list state cached across remounts.
  const servers = useAppSelector(selectMcpServers)
  const hasLoaded = useAppSelector(selectMcpHasLoaded)
  const isLoading = useAppSelector(selectMcpIsLoading) || !hasLoaded

  // Search and reload
  const [searchQuery, setSearchQuery] = useState('')
  const [isReloading, setIsReloading] = useState(false)

  // Add custom server modal state
  const [showAddModal, setShowAddModal] = useState(false)
  const [customJsonConfig, setCustomJsonConfig] = useState('')
  const [isAdding, setIsAdding] = useState(false)
  const [addError, setAddError] = useState('')

  // Configure env state
  const [configServer, setConfigServer] = useState<MCPServerConfig | null>(null)
  const [envValues, setEnvValues] = useState<Record<string, string>>({})
  const [isSavingEnv, setIsSavingEnv] = useState(false)

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Subscribe to side-effect messages (toasts, modal close). The list state
  // itself is updated by the slice via the registry.
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('mcp_enable', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (!d.success) showToast('error', d.error || t('settings:mcp.toast.enableFailed'))
      }),
      onMessage('mcp_disable', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (!d.success) showToast('error', d.error || t('settings:mcp.toast.disableFailed'))
      }),
      onMessage('mcp_remove', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (d.success) {
          showToast('success', d.message || t('settings:mcp.toast.removed'))
          send('mcp_list')
        } else {
          showToast('error', d.error || t('settings:mcp.toast.removeFailed'))
        }
      }),
      onMessage('mcp_add_json', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsAdding(false)
        if (d.success) {
          showToast('success', d.message || t('settings:mcp.toast.added'))
          setShowAddModal(false)
          setCustomJsonConfig('')
          setAddError('')
          send('mcp_list')
        } else {
          setAddError(d.error || t('settings:mcp.toast.addFailed'))
        }
      }),
      onMessage('mcp_get_env', (data: unknown) => {
        const d = data as { success: boolean; name: string; env?: Record<string, string> }
        if (d.success && d.env) setEnvValues(d.env)
      }),
      onMessage('mcp_update_env', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsSavingEnv(false)
        if (d.success) {
          showToast('success', d.message || t('settings:mcp.toast.configSaved'))
          setConfigServer(null)
          send('mcp_list')
        } else {
          showToast('error', d.error || t('settings:mcp.toast.configFailed'))
        }
      }),
    ]

    // Fetch list only on first mount (cached across re-mounts thereafter).
    if (!hasLoaded) {
      dispatch(setMcpLoading(true))
      send('mcp_list')
    }

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage, hasLoaded, dispatch, showToast])

  // Build MCP list
  const mcpList: MCPItem[] = servers
    .filter(s => {
      if (!searchQuery) return true
      return s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (s.description && s.description.toLowerCase().includes(searchQuery.toLowerCase()))
    })
    .map(s => ({
      name: s.name,
      description: s.description,
      enabled: s.enabled,
      transport: s.transport,
      action_set: s.action_set,
      env: s.env,
      needsConfig: s.env && Object.keys(s.env).length > 0 && Object.values(s.env).some(v => !v || v.trim() === '')
    }))
    .sort((a, b) => localeCompare(a.name, b.name))

  const totalServers = servers.length
  const enabledServers = servers.filter(s => s.enabled).length

  // Handlers
  const handleReloadServers = () => {
    setIsReloading(true)
    send('mcp_list')
    setTimeout(() => {
      setIsReloading(false)
      showToast('success', t('settings:mcp.toast.reloaded'))
    }, 500)
  }

  const handleToggleServer = (name: string, enabled: boolean) => {
    if (enabled) {
      send('mcp_enable', { name })
    } else {
      send('mcp_disable', { name })
    }
    dispatch(setMcpEnabled({ name, enabled }))
  }

  const handleRemoveServer = (name: string) => {
    confirm({
      title: t('settings:mcp.removeConfirmTitle'),
      message: t('settings:mcp.removeConfirmMessage', { name }),
      confirmText: t('common:actions.remove'),
      variant: 'danger',
    }, () => {
      send('mcp_remove', { name })
      dispatch(removeMcpServer(name))
    })
  }

  const handleConfigureServer = (server: MCPServerConfig) => {
    setConfigServer(server)
    setEnvValues({ ...server.env })
    send('mcp_get_env', { name: server.name })
  }

  const handleSaveEnv = () => {
    if (!configServer) return
    setIsSavingEnv(true)

    const envEntries = Object.entries(envValues)
    if (envEntries.length === 0) {
      setIsSavingEnv(false)
      setConfigServer(null)
      return
    }

    envEntries.forEach(([key, value]) => {
      send('mcp_update_env', { name: configServer.name, key, value })
    })
  }

  const handleAddCustomServer = () => {
    setAddError('')
    try {
      const config = JSON.parse(customJsonConfig)
      if (!config.name) {
        setAddError(t('settings:mcp.validation.nameRequired'))
        return
      }
      setIsAdding(true)
      send('mcp_add_json', { name: config.name, config: customJsonConfig })
    } catch {
      setAddError(t('settings:mcp.validation.invalidJson'))
    }
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitleRow}>
          <h3>{t('settings:mcp.title')}</h3>
          <Badge variant={enabledServers > 0 ? 'success' : 'default'}>
            {formatNumber(enabledServers)}/{formatNumber(totalServers)}
          </Badge>
        </div>
        <p>{t('settings:mcp.subtitle')}</p>
      </div>

      {/* Toolbar */}
      <div className={styles.mcpToolbar}>
        <div className={styles.mcpSearch}>
          <input
            type="text"
            placeholder={t('settings:mcp.search')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={styles.searchInput}
          />
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={handleReloadServers}
          disabled={isReloading}
          icon={isReloading ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          {t('settings:mcp.reload')}
        </Button>
      </div>

      {isLoading ? (
        <div className={styles.loadingState}>
          <Loader2 size={20} className={styles.spinning} />
          <span>{t('settings:mcp.loading')}</span>
        </div>
      ) : mcpList.length === 0 ? (
        <div className={styles.emptyState}>
          {searchQuery ? (
            <p>{t('settings:mcp.noMatch')}</p>
          ) : (
            <p>{t('settings:mcp.noneConfigured')}</p>
          )}
        </div>
      ) : (
        <div className={styles.mcpList}>
          {mcpList.map(item => (
            <div
              key={item.name}
              className={`${styles.mcpItem} ${!item.enabled ? styles.mcpItemDisabled : ''}`}
            >
              <div className={styles.mcpItemMain}>
                <div className={styles.mcpItemHeader}>
                  <span className={styles.mcpItemName}>{item.name}</span>
                  <Badge variant={item.enabled ? 'success' : 'default'}>
                    {item.enabled ? t('common:status.enabled') : t('common:status.disabled')}
                  </Badge>
                  {item.needsConfig && (
                    <Badge variant="warning">{t('settings:mcp.needsConfig')}</Badge>
                  )}
                </div>
                <p className={styles.mcpItemDesc}>{item.description}</p>
              </div>
              <div className={styles.mcpItemActions}>
                {item.env && Object.keys(item.env).length > 0 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      const server = servers.find(s => s.name === item.name)
                      if (server) handleConfigureServer(server)
                    }}
                    icon={<Edit2 size={14} />}
                    title={t('settings:mcp.configure')}
                  />
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemoveServer(item.name)}
                  icon={<Trash2 size={14} />}
                  title={t('settings:mcp.remove')}
                />
                <input
                  type="checkbox"
                  className={styles.toggle}
                  checked={item.enabled}
                  onChange={(e) => handleToggleServer(item.name, e.target.checked)}
                  title={item.enabled ? t('common:actions.disable') : t('common:actions.enable')}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add Server Section */}
      <div className={styles.mcpAddSection}>
        <Button
          variant="secondary"
          onClick={() => setShowAddModal(true)}
          icon={<Plus size={14} />}
        >
          {t('settings:mcp.addServer')}
        </Button>
        <span className={styles.hint}>{t('settings:mcp.addHint')}</span>
      </div>

      {/* Add Custom Server Modal */}
      {showAddModal && (
        <div className={styles.modalOverlay} onClick={() => { setShowAddModal(false); setAddError('') }}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>{t('settings:mcp.add.title')}</h3>
              <button className={styles.modalClose} onClick={() => { setShowAddModal(false); setAddError('') }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p className={styles.hint}>
                {t('settings:mcp.add.desc')}
              </p>
              <div className={styles.formGroup}>
                <label>{t('settings:mcp.add.label')}</label>
                <textarea
                  value={customJsonConfig}
                  onChange={(e) => setCustomJsonConfig(e.target.value)}
                  placeholder={`{
  "name": "my-server",
  "description": "My custom MCP server",
  "transport": "stdio",
  "command": "npx @my-org/my-mcp-server",
  "action_set": "default",
  "env": {}
}`}
                  rows={10}
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}
                />
              </div>
              {addError && (
                <div className={styles.errorText}>{addError}</div>
              )}
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => { setShowAddModal(false); setAddError('') }}>
                {t('common:actions.cancel')}
              </Button>
              <Button
                variant="primary"
                onClick={handleAddCustomServer}
                disabled={isAdding || !customJsonConfig.trim()}
              >
                {isAdding ? t('settings:mcp.add.adding') : t('settings:mcp.add.submit')}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Environment Configuration Modal */}
      {configServer && (
        <div className={styles.modalOverlay} onClick={() => setConfigServer(null)}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>{t('settings:mcp.env.title', { name: configServer.name })}</h3>
              <button className={styles.modalClose} onClick={() => setConfigServer(null)}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p className={styles.hint}>
                {t('settings:mcp.env.desc')}
              </p>
              {Object.keys(configServer.env).length === 0 ? (
                <p>{t('settings:mcp.env.none')}</p>
              ) : (
                Object.entries(configServer.env).map(([key]) => (
                  <div key={key} className={styles.formGroup}>
                    <label>{key}</label>
                    <input
                      type={key.toLowerCase().includes('key') || key.toLowerCase().includes('token') || key.toLowerCase().includes('secret') ? 'password' : 'text'}
                      value={envValues[key] || ''}
                      onChange={(e) => setEnvValues(prev => ({ ...prev, [key]: e.target.value }))}
                      placeholder={t('settings:mcp.env.placeholder', { key })}
                    />
                  </div>
                ))
              )}
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => setConfigServer(null)}>
                {t('common:actions.cancel')}
              </Button>
              <Button
                variant="primary"
                onClick={handleSaveEnv}
                disabled={isSavingEnv}
              >
                {isSavingEnv ? t('common:status.saving') : t('common:actions.save')}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Modal */}
      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
