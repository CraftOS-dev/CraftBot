import { useEffect } from 'react'
import { getSocketClient } from '../socket/socketInstance'
import { RESOURCES } from './catalog'
import { ResourceSync, type ResourceDescriptor } from './ResourceSync'

export { RESOURCES } from './catalog'
export type { ResourceDescriptor, ResourceName } from './ResourceSync'

/** The app's single ResourceSync, fed by the socket middleware. */
export const resourceSync = new ResourceSync(getSocketClient(), Object.values(RESOURCES))

/**
 * Keep `descriptor`'s data fresh while the calling component is mounted:
 * fetches it if it was never loaded or went stale, and refetches it whenever
 * the backend reports a change. Replaces fetch-once effects. Pass `null` to
 * stop using it (e.g. while a modal is closed).
 */
export function useResource(descriptor: ResourceDescriptor | null): void {
  useEffect(() => (descriptor ? resourceSync.subscribe(descriptor) : undefined), [descriptor])
}
