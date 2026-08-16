import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { TourController, type TourEnvironment } from './controller'
import type { TourEnvActionId, TourId } from './types'
import { TOURS } from './tours'
import { hasCompletedTour, resetTourCompletion } from './storage'
import 'driver.js/dist/driver.css'
import './tour.css'

interface TourContextValue {
  /** Start a tour now. `restart: true` clears its completed flag first. */
  startTour: (id: TourId, opts?: { restart?: boolean }) => void
  /**
   * Register a component capability the tour can invoke by name (e.g. a layout
   * expanding its sidebar). Returns an unregister function. Prefer the
   * `useTourEnvAction` hook, which wires cleanup automatically.
   */
  registerEnvAction: (id: TourEnvActionId, fn: (arg?: string) => void) => () => void
  isActive: boolean
}

const TourContext = createContext<TourContextValue | null>(null)

// Delay before a first-run tour auto-starts, letting the initial layout,
// fonts, and websocket-driven content settle so anchors are in place.
const AUTOSTART_DELAY_MS = 800

interface TourProviderProps {
  children: ReactNode
  /**
   * Gate for the one-time auto-start. The provider only auto-starts the core
   * tour when true — pass it once the app is past hard onboarding and ready.
   */
  autoStartEnabled?: boolean
}

export function TourProvider({ children, autoStartEnabled = false }: TourProviderProps) {
  const navigate = useNavigate()
  const location = useLocation()

  // Latest pathname, readable synchronously from controller callbacks.
  const pathnameRef = useRef(location.pathname)
  pathnameRef.current = location.pathname

  // Component capabilities the tour can invoke (see registerEnvAction).
  const envActionsRef = useRef<Map<TourEnvActionId, (arg?: string) => void>>(new Map())

  const controllerRef = useRef<TourController | null>(null)
  const [isActive, setIsActive] = useState(false)
  const autoStartedRef = useRef(false)

  const registerEnvAction = useCallback((id: TourEnvActionId, fn: (arg?: string) => void) => {
    envActionsRef.current.set(id, fn)
    return () => {
      // Only remove if still the same fn, so a newer registration isn't clobbered.
      if (envActionsRef.current.get(id) === fn) {
        envActionsRef.current.delete(id)
      }
    }
  }, [])

  const environment = useMemo<TourEnvironment>(() => ({
    navigate: (path: string) => navigate(path),
    getPathname: () => pathnameRef.current,
    runEnvAction: (id: TourEnvActionId, arg?: string) => {
      envActionsRef.current.get(id)?.(arg)
    },
  }), [navigate])

  const startTour = useCallback((id: TourId, opts?: { restart?: boolean }) => {
    const def = TOURS[id]
    if (!def) return
    if (controllerRef.current?.isActive()) return // never run two tours at once
    if (opts?.restart) resetTourCompletion(id)
    const controller = new TourController(def, environment, () => {
      controllerRef.current = null
      setIsActive(false)
    })
    controllerRef.current = controller
    setIsActive(true)
    void controller.start()
  }, [environment])

  // One-time auto-start of the core tour for first-time users. autoStartedRef
  // is set only when the timer actually fires, so StrictMode's mount/cleanup/
  // remount in dev reschedules cleanly instead of cancelling itself.
  useEffect(() => {
    if (!autoStartEnabled || autoStartedRef.current) return
    const def = TOURS.core
    if (!def.autoStart || hasCompletedTour('core')) return
    const timer = window.setTimeout(() => {
      autoStartedRef.current = true
      startTour('core')
    }, AUTOSTART_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [autoStartEnabled, startTour])

  // Tear down an in-flight tour if the provider unmounts.
  useEffect(() => () => {
    controllerRef.current?.destroy()
    controllerRef.current = null
  }, [])

  const value = useMemo<TourContextValue>(() => ({
    startTour,
    registerEnvAction,
    isActive,
  }), [startTour, registerEnvAction, isActive])

  return <TourContext.Provider value={value}>{children}</TourContext.Provider>
}

export function useTour(): TourContextValue {
  const ctx = useContext(TourContext)
  if (!ctx) throw new Error('useTour must be used within a TourProvider')
  return ctx
}

/**
 * Register a component capability the tour can invoke by name (e.g. a layout
 * expanding its sidebar so a nav item is visible). The latest `fn` is always
 * used, and it unregisters automatically on unmount.
 */
export function useTourEnvAction(id: TourEnvActionId, fn: (arg?: string) => void): void {
  const { registerEnvAction } = useTour()
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => registerEnvAction(id, (arg) => fnRef.current(arg)), [id, registerEnvAction])
}
