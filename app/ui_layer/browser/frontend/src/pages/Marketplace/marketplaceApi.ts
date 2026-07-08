import type { BannersResponse, CatalogQuery, CatalogResponse, MarketplaceProduct } from './types'

// The Python backend proxies these to the marketplace server and falls
// back to the public GitHub catalogue when it's unreachable — responses
// then carry degraded: true.

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) {
    let message = `Request failed (${resp.status})`
    try {
      const body = await resp.json()
      if (body?.error) message = body.error
    } catch { /* non-JSON error body */ }
    throw new Error(message)
  }
  return resp.json()
}

export function fetchCatalog(query: CatalogQuery = {}): Promise<CatalogResponse> {
  const params = new URLSearchParams()
  if (query.type) params.set('type', query.type)
  if (query.tag) params.set('tag', query.tag)
  if (query.q) params.set('q', query.q)
  if (query.featured) params.set('featured', 'true')
  if (query.sort) params.set('sort', query.sort)
  if (query.page) params.set('page', String(query.page))
  if (query.pageSize) params.set('pageSize', String(query.pageSize))
  const qs = params.toString()
  return getJson<CatalogResponse>(`/api/marketplace/catalog${qs ? `?${qs}` : ''}`)
}

export function fetchProduct(slug: string): Promise<MarketplaceProduct> {
  return getJson<MarketplaceProduct>(`/api/marketplace/products/${encodeURIComponent(slug)}`)
}

export function fetchBanners(): Promise<BannersResponse> {
  return getJson<BannersResponse>('/api/marketplace/banners')
}

async function sendJson<T>(method: 'PUT' | 'POST', url: string, body: unknown): Promise<T> {
  const resp = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok && resp.status !== 202) {
    let message = `Request failed (${resp.status})`
    try {
      const data = await resp.json()
      if (data?.error) message = data.error
    } catch { /* non-JSON error body */ }
    throw new Error(message)
  }
  return resp.json()
}

export interface RatingResponse {
  yourStars: number | null
  ratingAvg: number
  ratingCount: number
  /** True when the request carried a valid CraftBot Live/CraftOS session.
   *  OSS installs are always false — ratings/comments are read-only there. */
  authenticated?: boolean
}

export interface CommentItem {
  id: string
  displayName: string | null
  body: string
  createdAt: string
}

export interface CommentsResponse {
  comments: CommentItem[]
  total: number
  page: number
  pageSize: number
}

export function fetchRating(slug: string): Promise<RatingResponse> {
  return getJson<RatingResponse>(`/api/marketplace/products/${encodeURIComponent(slug)}/rating`)
}

export function submitRating(slug: string, stars: number): Promise<RatingResponse> {
  return sendJson<RatingResponse>('PUT', `/api/marketplace/products/${encodeURIComponent(slug)}/rating`, { stars })
}

export function fetchComments(slug: string, page = 1): Promise<CommentsResponse> {
  return getJson<CommentsResponse>(
    `/api/marketplace/products/${encodeURIComponent(slug)}/comments?page=${page}`,
  )
}

export function postComment(slug: string, body: string, displayName?: string): Promise<{ status: string }> {
  return sendJson<{ status: string }>(
    'POST',
    `/api/marketplace/products/${encodeURIComponent(slug)}/comments`,
    displayName ? { body, displayName } : { body },
  )
}

/** Display a version without SemVer build metadata: "0.0.0+main" → "0.0.0".
 *  The full string (with the +sha/+branch tag) still drives update detection. */
export function formatVersion(v?: string | null): string {
  return (v ?? '').split('+')[0]
}

export interface SkillInstallResponse {
  success: boolean
  message: string
}

export function installSkill(slug: string, gitUrl: string): Promise<SkillInstallResponse> {
  return sendJson<SkillInstallResponse>('POST', '/api/marketplace/skills/install', { slug, gitUrl })
}

/** Shape of /api/marketplace/bundles/stage — mirrors /api/profile/inspect. */
export interface BundleStageResponse {
  success: boolean
  error?: string
  bundle_token?: string
  manifest?: {
    name: string
    description?: string
    source_app_version?: string
    created_at?: string
    contents: {
      agent_name?: string
      md_files?: string[]
      skills?: string[]
      mcp_servers?: string[]
      living_ui_apps?: string[]
    }
  }
  preview?: {
    skills_already_installed: string[]
    mcp_already_installed: string[]
    mcp_needs_env: Array<{ name: string; env_keys: string[] }>
  }
}

export function stageBundle(downloadUrl: string): Promise<BundleStageResponse> {
  return sendJson<BundleStageResponse>('POST', '/api/marketplace/bundles/stage', { downloadUrl })
}

export function importBundle(
  bundleToken: string,
  mode: string,
  marketplaceSlug: string,
): Promise<{ success?: boolean; error?: string }> {
  return sendJson('POST', '/api/profile/import', {
    bundle_token: bundleToken,
    mode,
    marketplace_slug: marketplaceSlug,
  })
}

export interface MarketplaceEvent {
  slug: string
  type: 'view' | 'click' | 'install' | 'install_failed'
  metadata?: Record<string, unknown>
}

/** Best-effort engagement telemetry — never blocks or surfaces errors. */
export function reportEvents(events: MarketplaceEvent[]): void {
  if (events.length === 0) return
  fetch('/api/marketplace/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ events }),
    keepalive: true,
  }).catch(() => { /* telemetry is fire-and-forget */ })
}

// One view per product per session window. Also absorbs StrictMode's
// double-mounted effects in dev, which would otherwise report every
// product-page visit twice.
const reportedViews = new Map<string, number>()
const VIEW_DEDUPE_MS = 30 * 60 * 1000

export function reportProductView(slug: string): void {
  const last = reportedViews.get(slug)
  const now = Date.now()
  if (last !== undefined && now - last < VIEW_DEDUPE_MS) return
  reportedViews.set(slug, now)
  reportEvents([{ slug, type: 'view' }])
}
