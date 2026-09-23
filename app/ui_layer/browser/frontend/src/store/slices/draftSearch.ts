import { isDraft, original } from '@reduxjs/toolkit'

/**
 * `findIndex` for arrays inside reducers that doesn't read through the Immer
 * draft. Every element read via a draft creates a proxy, so a plain
 * `draft.findIndex` costs O(list size) proxies per event and froze the page
 * under bursts (docs/plans/ui-data-freshness-plan.md, RS-2.3). The original
 * array has the same order as the draft until the reducer changes it, so the
 * index addresses the draft too: search first, then mutate.
 */
export function findIndexInDraft<T>(list: T[], predicate: (item: T) => boolean): number {
  // `original` is typed for drafts of the state tree; this is a generic list.
  const plain = isDraft(list) ? (original(list as never) as T[] | undefined) ?? list : list
  return plain.findIndex(predicate)
}
