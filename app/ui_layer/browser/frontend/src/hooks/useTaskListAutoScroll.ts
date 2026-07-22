import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'

interface Pagination {
  hasMore: boolean
  loading: boolean
  loadMore: () => void
}

const NEAR_TOP_PX = 100
const NEAR_BOTTOM_PX = 100
const RECENT_SCROLL_GUARD_MS = 200

/**
 * Auto-scroll + scroll-to-bottom pagination for a non-virtualized list whose
 * items are rendered newest-at-top (active tasks above, ended tasks below).
 *
 * - On the first render with items present, jumps to the top (latest).
 * - When the item count grows, sticks to the top only if the user was near
 *   the top — if they scrolled down to inspect older entries, stays put.
 *   Suppressed while the user is actively scrolling so the auto-follow
 *   doesn't fight live wheel/trackpad input.
 * - When the user scrolls near the bottom, calls `loadMore()`. Items are
 *   always appended below the current view (lists are newest-at-top,
 *   oldest-at-bottom, and `loadMore()` only fetches older items), so the
 *   existing scrollTop stays valid on its own — no restore is performed.
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
  // Tracked alongside wasNearTopRef so the auto-follow below can tell a
  // genuine "near top" apart from a short list where the whole scrollable
  // range fits inside NEAR_TOP_PX, making "near top" and "near bottom" true
  // simultaneously.
  const wasNearBottomRef = useRef(false)
  const hasInitialScrolledRef = useRef(false)
  const prevItemCountRef = useRef(0)
  const prevLoadingRef = useRef(false)
  // Guards against re-triggering loadMore() while a request is already in
  // flight; self-healing (cleared whenever `loading` is false) so it can't
  // wedge shut if loadMore() bails out internally without ever setting
  // `loading` true.
  const loadInFlightRef = useRef(false)
  // Timestamp of the last scroll event, used to suppress the near-top
  // auto-follow while the user is actively scrolling.
  const lastScrollAtRef = useRef(0)

  // Mirror latest pagination props into a ref so the scroll listener doesn't
  // tear down and re-attach on every render of the parent.
  const paginationRef = useRef({ hasMore, loading, loadMore })
  paginationRef.current = { hasMore, loading, loadMore }

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const handleScroll = () => {
      lastScrollAtRef.current = Date.now()
      wasNearTopRef.current = el.scrollTop < NEAR_TOP_PX
      const { hasMore: hm, loading: ld, loadMore: lm } = paginationRef.current
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      wasNearBottomRef.current = distFromBottom < NEAR_BOTTOM_PX
      if (distFromBottom < NEAR_BOTTOM_PX && hm && !ld && !loadInFlightRef.current) {
        loadInFlightRef.current = true
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

    if (!loading) {
      loadInFlightRef.current = false
    }

    // Pagination just finished: items were appended below the current
    // viewport, so the existing scrollTop is already correct — nothing to
    // restore.
    if (wasLoading && !loading) {
      return
    }

    // First render with items: jump to the top (latest).
    if (!hasInitialScrolledRef.current && itemCount > 0) {
      el.scrollTop = 0
      hasInitialScrolledRef.current = true
      wasNearTopRef.current = true
      return
    }

    // New item while the user was following the head — auto-follow to top,
    // unless the user is actively mid-scroll (avoids fighting live input) or
    // the list is short enough that "near top" and "near bottom" overlap
    // (avoids fighting an in-progress bottom pagination).
    if (
      grew &&
      wasNearTopRef.current &&
      !wasNearBottomRef.current &&
      Date.now() - lastScrollAtRef.current > RECENT_SCROLL_GUARD_MS
    ) {
      el.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [itemCount, loading, ref])
}
