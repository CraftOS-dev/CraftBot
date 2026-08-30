import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, RefreshCw, Eye, Wrench, Database, ExternalLink } from 'lucide-react'
import { formatNumber } from '../../i18n/format'
import styles from './SettingsPage.module.css'

export interface OpenRouterModel {
  id: string
  canonical_slug: string | null
  name: string
  description: string
  context_length: number | null
  input_modalities: string[]
  output_modalities: string[]
  pricing: {
    prompt: string | null
    completion: string | null
    image: string | null
    input_cache_read: string | null
    input_cache_write: string | null
  }
  supported_parameters: string[]
  is_moderated: boolean | null
}

export interface OpenRouterCredits {
  balance: number | null
  usage: number
  limit: number | null
  label: string | null
  is_free_tier: boolean | null
}

type WsSend = (type: string, data?: Record<string, unknown>) => void
type WsOnMessage = (type: string, handler: (data: unknown) => void) => () => void

// ─────────────────────────────────────────────────────────────────────
// Hooks: catalog and credits
// ─────────────────────────────────────────────────────────────────────

export function useOpenRouterCatalog(
  send: WsSend,
  onMessage: WsOnMessage,
  isConnected: boolean,
  enabled: boolean,
  baseUrl?: string,
) {
  const [models, setModels] = useState<OpenRouterModel[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<number | null>(null)
  const requestedRef = useRef(false)
  const prevBaseUrlRef = useRef(baseUrl)
  const { t } = useTranslation(['settings'])

  useEffect(() => {
    const cleanup = onMessage('openrouter_models_get', (data: unknown) => {
      const d = data as { success: boolean; models?: OpenRouterModel[]; error?: string; fetched_at?: number }
      setLoading(false)
      if (d.success && d.models) {
        setModels(d.models)
        setError(null)
        if (d.fetched_at) setFetchedAt(d.fetched_at)
      } else {
        setError(d.error || t('settings:model.orPicker.loadModelsFailed'))
      }
    })
    return cleanup
  }, [onMessage, t])

  // Fetch once after we go enabled+connected. Re-fetch when baseUrl changes.
  useEffect(() => {
    // Reset the guard when baseUrl changes so the new endpoint is fetched.
    if (prevBaseUrlRef.current !== baseUrl) {
      prevBaseUrlRef.current = baseUrl
      requestedRef.current = false
    }
    if (!isConnected || !enabled || requestedRef.current) return
    requestedRef.current = true
    setLoading(true)
    setError(null)
    send('openrouter_models_get', baseUrl ? { baseUrl } : {})
  }, [isConnected, enabled, baseUrl, send])

  const refresh = () => {
    setLoading(true)
    setError(null)
    send('openrouter_models_get', { ...(baseUrl ? { baseUrl } : {}), forceRefresh: true })
  }

  return { models, loading, error, fetchedAt, refresh }
}

export function useOpenRouterCredits(
  send: WsSend,
  onMessage: WsOnMessage,
  isConnected: boolean,
  hasApiKey: boolean,
) {
  const [credits, setCredits] = useState<OpenRouterCredits | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { t } = useTranslation(['settings'])

  useEffect(() => {
    const cleanup = onMessage('openrouter_credits_get', (data: unknown) => {
      const d = data as {
        success: boolean
        balance?: number | null
        usage?: number
        limit?: number | null
        label?: string | null
        is_free_tier?: boolean | null
        error?: string
      }
      setLoading(false)
      if (d.success) {
        setCredits({
          balance: d.balance ?? null,
          usage: d.usage ?? 0,
          limit: d.limit ?? null,
          label: d.label ?? null,
          is_free_tier: d.is_free_tier ?? null,
        })
        setError(null)
      } else {
        setCredits(null)
        setError(d.error || t('settings:model.orPicker.loadCreditsFailed'))
      }
    })
    return cleanup
  }, [onMessage, t])

  useEffect(() => {
    if (!isConnected || !hasApiKey) {
      setCredits(null)
      return
    }
    setLoading(true)
    send('openrouter_credits_get')
  }, [isConnected, hasApiKey, send])

  return { credits, loading, error }
}

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────

function formatPricePerMillion(p: string | null | undefined): string | null {
  if (p == null) return null
  const n = parseFloat(p)
  if (isNaN(n)) return null
  if (n === 0) return null
  const perM = n * 1_000_000
  if (perM >= 100) return `$${perM.toFixed(0)}`
  if (perM >= 1) return `$${perM.toFixed(2)}`
  if (perM >= 0.01) return `$${perM.toFixed(3)}`
  return `$${perM.toFixed(4)}`
}

function isFreeModel(m: OpenRouterModel): boolean {
  if (m.id.endsWith(':free')) return true
  const p = parseFloat(m.pricing.prompt || '0')
  const c = parseFloat(m.pricing.completion || '0')
  return (isNaN(p) || p === 0) && (isNaN(c) || c === 0)
}

function supportsVision(m: OpenRouterModel): boolean {
  return m.input_modalities.includes('image')
}

function supportsTools(m: OpenRouterModel): boolean {
  return m.supported_parameters.includes('tools') || m.supported_parameters.includes('tool_choice')
}

function supportsCache(m: OpenRouterModel): boolean {
  return Boolean(m.pricing.input_cache_read)
}

function upstreamOf(id: string): string {
  const slash = id.indexOf('/')
  return slash > 0 ? id.slice(0, slash) : id
}

function formatContext(n: number | null | undefined): string {
  if (n == null) return ''
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`
  return `${n}`
}

// ─────────────────────────────────────────────────────────────────────
// Credits banner
// ─────────────────────────────────────────────────────────────────────

interface CreditsBannerProps {
  send: WsSend
  onMessage: WsOnMessage
  isConnected: boolean
  hasApiKey: boolean
}

export function OpenRouterCreditsBanner({ send, onMessage, isConnected, hasApiKey }: CreditsBannerProps) {
  const { t } = useTranslation(['settings'])
  const { credits, loading, error } = useOpenRouterCredits(send, onMessage, isConnected, hasApiKey)

  if (!hasApiKey) {
    return (
      <div className={styles.orCreditsRow}>
        <span className={styles.orCreditsLabel}>
          {t('settings:model.orPicker.saveKeyForCredits')}
        </span>
        <a
          className={styles.orCreditsLink}
          href="https://openrouter.ai/keys"
          target="_blank"
          rel="noreferrer"
        >
          {t('settings:model.orPicker.getKey')} <ExternalLink size={12} />
        </a>
      </div>
    )
  }

  if (loading) {
    return (
      <div className={styles.orCreditsRow}>
        <span className={styles.orCreditsLabel}>
          <Loader2 size={12} className={styles.spinning} /> {t('settings:model.orPicker.loadingCredits')}
        </span>
      </div>
    )
  }

  if (error) {
    return (
      <div className={styles.orCreditsRow}>
        <span className={styles.orCreditsLabel}>{t('settings:model.orPicker.creditsError', { error })}</span>
      </div>
    )
  }

  if (!credits) return null

  const balanceText = credits.balance != null
    ? t('settings:model.orPicker.balanceRemaining', { amount: formatNumber(credits.balance, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })
    : t('settings:model.orPicker.payAsYouGo')

  return (
    <div className={styles.orCreditsRow}>
      <span className={styles.orCreditsLabel}>
        {t('settings:model.orPicker.creditsLabel')} <strong>{balanceText}</strong>
        {credits.label ? <span className={styles.orCreditsKey}> · {credits.label}</span> : null}
      </span>
      <a
        className={styles.orCreditsLink}
        href="https://openrouter.ai/credits"
        target="_blank"
        rel="noreferrer"
      >
        {t('settings:model.orPicker.topUp')} <ExternalLink size={12} />
      </a>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Model picker
// ─────────────────────────────────────────────────────────────────────

interface PickerProps {
  models: OpenRouterModel[]
  loading: boolean
  error: string | null
  value: string
  onChange: (v: string) => void
  onRefresh: () => void
  requireVision?: boolean
  label: string
}

export function OpenRouterModelPicker({
  models,
  loading,
  error,
  value,
  onChange,
  onRefresh,
  requireVision = false,
  label,
}: PickerProps) {
  const { t } = useTranslation(['settings', 'common'])
  const [search, setSearch] = useState('')
  const [filterFree, setFilterFree] = useState(false)
  const [filterVision, setFilterVision] = useState(requireVision)
  const [filterTools, setFilterTools] = useState(false)
  const [filterCache, setFilterCache] = useState(false)
  const [upstream, setUpstream] = useState<string>('')

  // VLM picker should keep the vision filter pinned on
  useEffect(() => {
    if (requireVision) setFilterVision(true)
  }, [requireVision])

  const upstreams = useMemo(() => {
    const set = new Set<string>()
    for (const m of models) set.add(upstreamOf(m.id))
    return Array.from(set).sort()
  }, [models])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return models.filter(m => {
      if (filterFree && !isFreeModel(m)) return false
      if (filterVision && !supportsVision(m)) return false
      if (filterTools && !supportsTools(m)) return false
      if (filterCache && !supportsCache(m)) return false
      if (upstream && upstreamOf(m.id) !== upstream) return false
      if (!q) return true
      return (
        m.id.toLowerCase().includes(q) ||
        m.name.toLowerCase().includes(q) ||
        (m.description || '').toLowerCase().includes(q)
      )
    })
  }, [models, search, filterFree, filterVision, filterTools, filterCache, upstream])

  return (
    <div className={styles.formGroup}>
      <label>{label}</label>

      <div className={styles.orPicker}>
        <div className={styles.orPickerHeader}>
          <input
            type="text"
            className={styles.searchInput}
            placeholder={t('settings:model.orPicker.searchModels', { count: models.length })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button
            type="button"
            className={styles.orPickerRefreshBtn}
            onClick={onRefresh}
            title={t('settings:model.orPicker.refreshCatalog')}
            disabled={loading}
          >
            {loading ? <Loader2 size={14} className={styles.spinning} /> : <RefreshCw size={14} />}
          </button>
        </div>

        <div className={styles.orPickerFilters}>
          <button
            type="button"
            className={`${styles.orPickerChip} ${filterFree ? styles.orPickerChipActive : ''}`}
            onClick={() => setFilterFree(v => !v)}
            aria-pressed={filterFree}
          >
            {t('settings:model.orPicker.freeOnly')}
          </button>
          <button
            type="button"
            className={`${styles.orPickerChip} ${filterVision ? styles.orPickerChipActive : ''}`}
            onClick={() => !requireVision && setFilterVision(v => !v)}
            aria-pressed={filterVision}
            disabled={requireVision}
            title={requireVision ? t('settings:model.orPicker.visionRequired') : undefined}
          >
            {t('settings:model.orPicker.vision')}
          </button>
          <button
            type="button"
            className={`${styles.orPickerChip} ${filterTools ? styles.orPickerChipActive : ''}`}
            onClick={() => setFilterTools(v => !v)}
            aria-pressed={filterTools}
          >
            {t('settings:model.orPicker.tools')}
          </button>
          <button
            type="button"
            className={`${styles.orPickerChip} ${filterCache ? styles.orPickerChipActive : ''}`}
            onClick={() => setFilterCache(v => !v)}
            aria-pressed={filterCache}
          >
            {t('settings:model.orPicker.caching')}
          </button>
          <select
            className={styles.orPickerUpstream}
            value={upstream}
            onChange={(e) => setUpstream(e.target.value)}
          >
            <option value="">{t('settings:model.orPicker.anyUpstream')}</option>
            {upstreams.map(u => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
        </div>

        <div className={styles.orPickerList}>
          {loading && models.length === 0 && (
            <div className={styles.orPickerStatus}>
              <Loader2 size={14} className={styles.spinning} /> {t('settings:model.orPicker.loadingCatalog')}
            </div>
          )}
          {error && (
            <div className={styles.orPickerError}>
              {error}
              <button type="button" onClick={onRefresh}>{t('common:actions.retry')}</button>
            </div>
          )}
          {!loading && !error && filtered.length === 0 && (
            <div className={styles.orPickerStatus}>
              {t('settings:model.orPicker.noModels')}
            </div>
          )}
          {filtered.map(m => {
            const free = isFreeModel(m)
            const promptPrice = formatPricePerMillion(m.pricing.prompt)
            const completionPrice = formatPricePerMillion(m.pricing.completion)
            const ctxStr = formatContext(m.context_length)
            const selected = value === m.id
            return (
              <button
                key={m.id}
                type="button"
                className={`${styles.orPickerRow} ${selected ? styles.orPickerRowSelected : ''}`}
                onClick={() => onChange(m.id)}
              >
                <div className={styles.orPickerRowLeft}>
                  <div className={styles.orPickerRowName}>{m.name}</div>
                  <div className={styles.orPickerRowSlug}>{m.id}</div>
                </div>
                <div className={styles.orPickerRowRight}>
                  <div className={styles.orPickerRowMeta}>
                    {ctxStr && <span className={styles.orPickerCtx}>{t('settings:model.orPicker.ctx', { ctx: ctxStr })}</span>}
                    {supportsVision(m) && (
                      <span className={styles.orPickerCap} title={t('settings:model.orPicker.visionCapable')}>
                        <Eye size={12} />
                      </span>
                    )}
                    {supportsTools(m) && (
                      <span className={styles.orPickerCap} title={t('settings:model.orPicker.toolCalling')}>
                        <Wrench size={12} />
                      </span>
                    )}
                    {supportsCache(m) && (
                      <span className={styles.orPickerCap} title={t('settings:model.orPicker.promptCaching')}>
                        <Database size={12} />
                      </span>
                    )}
                  </div>
                  <div className={styles.orPickerRowPrice}>
                    {free ? (
                      <span className={styles.orPickerFreeBadge}>{t('settings:model.orPicker.free')}</span>
                    ) : promptPrice && completionPrice ? (
                      <span>{t('settings:model.orPicker.price', { prompt: promptPrice, completion: completionPrice })} <span className={styles.orPickerPriceUnit}>{t('settings:model.orPicker.priceUnit')}</span></span>
                    ) : (
                      <span className={styles.orPickerPriceUnit}>{t('settings:model.orPicker.seeOpenRouter')}</span>
                    )}
                  </div>
                </div>
              </button>
            )
          })}
        </div>

        <div className={styles.orPickerSlug}>
          <label>{t('settings:model.orPicker.pasteSlug')}</label>
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="anthropic/claude-sonnet-4.5"
          />
        </div>
      </div>
    </div>
  )
}
