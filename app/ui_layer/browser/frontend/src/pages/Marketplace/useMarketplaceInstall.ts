import { useCallback, useEffect, useRef, useState } from 'react'
import { useSettingsWebSocket } from '../Settings/useSettingsWebSocket'
import { fetchProduct, importBundle, installSkill, stageBundle } from './marketplaceApi'
import type { BundleStageResponse } from './marketplaceApi'
import type { MarketplaceProduct } from './types'

const INSTALL_TIMEOUT_MS = 3 * 60 * 1000

export interface StagedBundle {
  slug: string
  productName: string
  token: string
  manifest: NonNullable<BundleStageResponse['manifest']>
  preview: NonNullable<BundleStageResponse['preview']>
}

/**
 * Install flows for all three product types, shared by grid and detail page.
 *
 * - living_ui: WS living_ui_marketplace_install (pinned version when known);
 *   keeps running server-side if the user navigates away.
 * - skill: git-clone through the backend, awaited inline.
 * - agent_bundle: download + inspect ("stage"), then a Replace/Merge confirm
 *   dialog applies it via the existing profile import endpoint.
 */
export function useMarketplaceInstall() {
  const { send, onMessage } = useSettingsWebSocket()
  const [installingIds, setInstallingIds] = useState<Set<string>>(new Set())
  const [installedIds, setInstalledIds] = useState<Set<string>>(new Set())
  const [installError, setInstallError] = useState<string | null>(null)
  const [configuring, setConfiguring] = useState<MarketplaceProduct | null>(null)
  const [stagedBundle, setStagedBundle] = useState<StagedBundle | null>(null)
  const [bundleApplying, setBundleApplying] = useState(false)
  const [bundleError, setBundleError] = useState<string | null>(null)
  const timeoutsRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  useEffect(() => () => { timeoutsRef.current.forEach(t => clearTimeout(t)) }, [])

  useEffect(() => {
    return onMessage('living_ui_marketplace_install', (raw: unknown) => {
      const data = raw as { status?: string; appId?: string; error?: string }
      const appId = data.appId
      const clear = (id: string) => {
        const t = timeoutsRef.current.get(id)
        if (t) { clearTimeout(t); timeoutsRef.current.delete(id) }
        setInstallingIds(prev => { const n = new Set(prev); n.delete(id); return n })
      }
      if (appId) clear(appId)
      else {
        timeoutsRef.current.forEach(t => clearTimeout(t))
        timeoutsRef.current.clear()
        setInstallingIds(new Set())
      }
      // Install/install_failed telemetry is reported by the Python backend
      // (it sees the result even after this page unmounts).
      if (data.status === 'success') {
        if (appId) setInstalledIds(prev => new Set(prev).add(appId))
      } else {
        setInstallError(data.error || 'Installation failed')
      }
    })
  }, [onMessage])

  const setBusy = (appId: string, busy: boolean) => {
    setInstallingIds(prev => {
      const n = new Set(prev)
      if (busy) n.add(appId)
      else n.delete(appId)
      return n
    })
  }

  const doInstall = useCallback((product: MarketplaceProduct, fields: Record<string, string>) => {
    const appId = product.repoPath || product.slug
    setConfiguring(null)
    setInstallError(null)
    setInstallingIds(prev => new Set(prev).add(appId))

    const timeout = setTimeout(() => {
      timeoutsRef.current.delete(appId)
      setInstallingIds(prev => { const n = new Set(prev); n.delete(appId); return n })
      setInstallError(`Installation of "${product.name}" timed out. Please try again.`)
    }, INSTALL_TIMEOUT_MS)
    timeoutsRef.current.set(appId, timeout)

    const latest = product.versions?.find(v => v.isLatest)
    send('living_ui_marketplace_install', {
      appId,
      appName: fields.APP_TITLE || product.name,
      appDescription: product.tagline || product.descriptionMd || '',
      customFields: fields,
      slug: product.slug,
      version: latest?.version ?? product.latestVersion,
      downloadUrl: latest?.downloadUrl,
      gitCommitSha: latest?.gitCommitSha,
    })
  }, [send])

  const installSkillProduct = useCallback(async (product: MarketplaceProduct) => {
    const appId = product.repoPath || product.slug
    const gitUrl = product.versions?.find(v => v.isLatest)?.downloadUrl
    if (!gitUrl) {
      setInstallError(`"${product.name}" has no source URL yet — it can't be installed.`)
      return
    }
    setInstallError(null)
    setBusy(appId, true)
    try {
      const result = await installSkill(product.slug, gitUrl)
      if (result.success) {
        setInstalledIds(prev => new Set(prev).add(appId))
      } else {
        setInstallError(result.message || 'Skill installation failed')
      }
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : 'Skill installation failed')
    } finally {
      setBusy(appId, false)
    }
  }, [])

  const stageBundleProduct = useCallback(async (product: MarketplaceProduct) => {
    const appId = product.repoPath || product.slug
    const downloadUrl = product.versions?.find(v => v.isLatest)?.downloadUrl
    if (!downloadUrl) {
      setInstallError(`"${product.name}" has no bundle file yet — it can't be installed.`)
      return
    }
    setInstallError(null)
    setBundleError(null)
    setBusy(appId, true)
    try {
      const result = await stageBundle(downloadUrl)
      if (result.success && result.bundle_token && result.manifest && result.preview) {
        setStagedBundle({
          slug: product.slug,
          productName: product.name,
          token: result.bundle_token,
          manifest: result.manifest,
          preview: result.preview,
        })
      } else {
        setInstallError(result.error || 'Could not read this bundle')
      }
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : 'Bundle download failed')
    } finally {
      setBusy(appId, false)
    }
  }, [])

  /** Apply a staged bundle (called from the Replace/Merge confirm dialog). */
  const applyBundle = useCallback(async (mode: string) => {
    if (!stagedBundle) return
    setBundleApplying(true)
    setBundleError(null)
    try {
      const result = await importBundle(stagedBundle.token, mode, stagedBundle.slug)
      if (result.error) {
        setBundleError(result.error)
      } else {
        setInstalledIds(prev => new Set(prev).add(stagedBundle.slug))
        setStagedBundle(null)
      }
    } catch (err) {
      setBundleError(err instanceof Error ? err.message : 'Bundle import failed')
    } finally {
      setBundleApplying(false)
    }
  }, [stagedBundle])

  /** Entry point from an Install button — dispatches by product type. */
  const requestInstall = useCallback(async (product: MarketplaceProduct) => {
    // Cards don't carry versions/customFields — resolve the full detail first.
    let resolved = product
    if (!product.versions && !product.degraded) {
      try {
        resolved = await fetchProduct(product.slug)
      } catch { /* fall through with the card data */ }
    }
    if (resolved.type === 'skill') {
      await installSkillProduct(resolved)
    } else if (resolved.type === 'agent_bundle') {
      await stageBundleProduct(resolved)
    } else if (resolved.customFields && resolved.customFields.length > 0) {
      setConfiguring(resolved)
    } else {
      doInstall(resolved, {})
    }
  }, [doInstall, installSkillProduct, stageBundleProduct])

  return {
    installingIds,
    installedIds,
    installError,
    setInstallError,
    configuring,
    setConfiguring,
    requestInstall,
    doInstall,
    stagedBundle,
    setStagedBundle,
    applyBundle,
    bundleApplying,
    bundleError,
  }
}
