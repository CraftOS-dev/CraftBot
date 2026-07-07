export type ProductType = 'living_ui' | 'skill' | 'agent_bundle'

export interface ProductStats {
  views: number
  clicks: number
  downloads: number
  ratingAvg: number
  ratingCount: number
}

export interface CustomField {
  key: string
  label: string
  type: string
  default: string
  placeholder?: string
}

export interface ProductVersion {
  version: string
  gitCommitSha?: string
  downloadUrl?: string
  changelogMd?: string
  isLatest: boolean
  publishedAt?: string
}

export interface ProductCreator {
  name: string
  githubHandle?: string
  url?: string
}

export interface MarketplaceProduct {
  slug: string
  type: ProductType
  name: string
  tagline?: string
  descriptionMd?: string
  previewUrl?: string | null
  screenshots?: string[]
  tags: string[]
  approved: boolean
  featured: boolean
  /** Folder inside the living-ui-marketplace repo — the install appId */
  repoPath?: string
  customFields?: CustomField[]
  latestVersion?: string
  creator?: ProductCreator | null
  versions?: ProductVersion[]
  stats: ProductStats
  degraded?: boolean
}

export interface CatalogResponse {
  products: MarketplaceProduct[]
  total: number
  page: number
  pageSize: number
  /** True when served from the GitHub fallback (marketplace server unreachable) */
  degraded: boolean
}

export interface Banner {
  slot: 'hero' | 'shelf'
  title: string
  subtitle?: string
  imageUrl?: string
  ctaUrl?: string
  productSlug?: string
  sortOrder: number
}

export interface BannersResponse {
  banners: Banner[]
  degraded?: boolean
}

export interface CatalogQuery {
  type?: ProductType
  tag?: string
  q?: string
  featured?: boolean
  sort?: 'downloads' | 'rating' | 'recent'
  page?: number
  pageSize?: number
}
