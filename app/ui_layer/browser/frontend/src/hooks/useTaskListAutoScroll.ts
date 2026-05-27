import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'

interface Pagination {
  hasMore: boolean
  loading: boolean
  loadMore: () => void
}

const NEAR_BOTTOM_PX = 100
const NEAR_TOP_PX = 100

/**
 * Auto-scroll + scroll-to-top pagination for a non-virtualized list whose
 * items arrive chronologically (newest at the bottom).
 *
 * - On the first render with items present, jumps to the bottom (latest).
 * - When the item count grows, sticks to the bottom only if the user was
 *   near the bottom — if they scrolled up to read older entries, stays put.
 * - When the user scrolls near the top, calls `loadMore()` and preserves
 *   the visible anchor so freshly prepended items don't yank the viewport.
 *
 * Shared by ChatPage's Tasks & Actions sidebar and TasksPage's All Tasks
 * list so the two stay in sync.
 */
export function useTaskListAutoScroll<T extends HTMLElement>(
  ref: RefObject<T | null>,
  itemCount: number,
  { hasMore, loading, loadMore }: Pagination,
): void {
  const wasNearBottomRef = useRef(true)
  const hasInitialScrolledRef = useRef(false)
  const prevItemCountRef = useRef(0)
  const prevLoadingRef = useRef(false)
  // Captured on scroll-to-top before triggering pagination; cleared by the
  // layout effect once the prepended items have shifted the viewport.
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
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      wasNearBottomRef.current = distFromBottom < NEAR_BOTTOM_PX
      const { hasMore: hm, loading: ld, loadMore: lm } = paginationRef.current
      if (
        el.scrollTop < NEAR_TOP_PX &&
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

    // Pagination just finished (loading true→false): restore the anchor so
    // the user is still looking at the item they were on when they triggered
    // the load. Runs whether the response added items or was empty.
    if (
      wasLoading &&
      !loading &&
      pendingRestoreScrollHeightRef.current !== null &&
      pendingRestoreScrollTopRef.current !== null
    ) {
      const diff = el.scrollHeight - pendingRestoreScrollHeightRef.current
      el.scrollTop = pendingRestoreScrollTopRef.current + diff
      pendingRestoreScrollHeightRef.current = null
      pendingRestoreScrollTopRef.current = null
      return
    }

    // First render with items: jump to the bottom (latest).
    if (!hasInitialScrolledRef.current && itemCount > 0) {
      el.scrollTop = el.scrollHeight
      hasInitialScrolledRef.current = true
      wasNearBottomRef.current = true
      return
    }

    // New item while the user was following the tail — auto-follow.
    if (grew && wasNearBottomRef.current) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }
  }, [itemCount, loading, ref])
}
