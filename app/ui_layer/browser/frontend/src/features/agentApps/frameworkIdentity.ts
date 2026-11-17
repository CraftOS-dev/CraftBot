export const frameworkKey = (path: string, id: string) => `framework:${JSON.stringify([path, id])}`
export const frameworkRoute = (path: string, id: string) => `/framework-app?${new URLSearchParams({ path, id })}`

/** A conversation's persisted identity includes the profile before path/id. */
export function frameworkSessionIdentity(key?: string | null): { path: string; appId: string } | null {
  try {
    const [, path, appId] = JSON.parse(key || '')
    return typeof path === 'string' && path && typeof appId === 'string' && appId ? { path, appId } : null
  } catch { return null }
}
