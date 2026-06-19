import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'

interface Pagination {
  hasMore: boolean
  loading: boolean
  loadMore: () => void
}

const NEAR_TOP_PX = 100
const NEAR_BOTTOM_PX = 100

/**
 * Auto-scroll + scroll-to-bottom pagination for a non-virtualized list whose
 * items are rendered newest-at-top (active tasks above, ended tasks below).
 *
 * - On the first render with items present, jumps to the top (latest).
 * - When the item count grows, sticks to the top only if the user was near
 *   the top — if they scrolled down to inspect older entries, stays put.
 * - When the user scrolls near the bottom, calls `loadMore()` and preserves
 *   the visible anchor so freshly appended items don't yank the viewport.
 *
 * Shared by ChatPage's Tasks & Actions sidebar and TasksPage's All Tasks
 * list so the two stay in sync.
 */
export function useTaskListAutoScroll<T extends HTMLElement>(
  ref: RefObject<T | null>,
  itemCount: number,
  { hasMore, loading, loadMore }: Pagination,
): void {
  const wasNearTopRef = useRef(true)
  const hasInitialScrolledRef = useRef(false)
  const prevItemCountRef = useRef(0)
  const prevLoadingRef = useRef(false)
  // Captured on scroll-to-bottom before triggering pagination; cleared by the
  // layout effect once the appended items have settled.
  const pendingRestoreScrollTopRef = useRef<number | null>(null)
  const pendingRestoreScrollHeightRef = useRef<number | null>(null)

  // Mirror latest pagination props into a ref so the scroll listener doesn't
  // tear down and re-attach on every render of the parent.
  const paginationRef = useRef({ hasMore, loading, loadMore })
  paginationRef.current = { hasMore, loading, loadMore }

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const handleScroll = () => {
      wasNearTopRef.current = el.scrollTop < NEAR_TOP_PX
      const { hasMore: hm, loading: ld, loadMore: lm } = paginationRef.current
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      if (
        distFromBottom < NEAR_BOTTOM_PX &&
        hm &&
        !ld &&
        pendingRestoreScrollHeightRef.current === null
      ) {
        pendingRestoreScrollTopRef.current = el.scrollTop
        pendingRestoreScrollHeightRef.current = el.scrollHeight
        lm()
      }
    }
    el.addEventListener('scroll', handleScroll)
    return () => el.removeEventListener('scroll', handleScroll)
  }, [ref])

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return

    const wasLoading = prevLoadingRef.current
    prevLoadingRef.current = loading
    const grew = itemCount > prevItemCountRef.current
    prevItemCountRef.current = itemCount

    // Pagination just finished (loading true→false): keep the user anchored
    // where they were when they triggered the load. Newly appended items
    // grow scrollHeight; preserving scrollTop alone is enough.
    if (
      wasLoading &&
      !loading &&
      pendingRestoreScrollHeightRef.current !== null &&
      pendingRestoreScrollTopRef.current !== null
    ) {
      el.scrollTop = pendingRestoreScrollTopRef.current
      pendingRestoreScrollHeightRef.current = null
      pendingRestoreScrollTopRef.current = null
      return
    }

    // First render with items: jump to the top (latest).
    if (!hasInitialScrolledRef.current && itemCount > 0) {
      el.scrollTop = 0
      hasInitialScrolledRef.current = true
      wasNearTopRef.current = true
      return
    }

    // New item while the user was following the head — auto-follow to top.
    if (grew && wasNearTopRef.current) {
      el.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [itemCount, loading, ref])
}
