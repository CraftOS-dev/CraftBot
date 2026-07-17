/**
 * AuthProvider — pb.authStore-backed auth context.
 *
 * Copy into frontend/components/auth/. PocketBase's SDK persists the auth
 * token in localStorage and this provider mirrors it into React state, so
 * the session survives reloads with zero extra wiring.
 */
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import { pb } from '@/lib/pb'

export interface AuthUser {
  id: string
  email: string
  name: string
  role: 'admin' | 'member' | ''
}

interface AuthContextValue {
  user: AuthUser | null
  isAuthenticated: boolean
  isAdmin: boolean
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

function toAuthUser(record: unknown): AuthUser | null {
  const r = record as Record<string, unknown> | null
  if (!r || !r.id) return null
  return {
    id: String(r.id),
    email: String(r.email ?? ''),
    name: String(r.name ?? ''),
    role: (r.role as AuthUser['role']) ?? '',
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() =>
    toAuthUser(pb.authStore.record),
  )
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Keep React state in lockstep with the SDK's auth store.
    const unsubscribe = pb.authStore.onChange(() => {
      setUser(toAuthUser(pb.authStore.record))
    })
    // Validate a persisted token on boot (clears it when stale).
    ;(async () => {
      if (pb.authStore.isValid) {
        try {
          await pb.collection('users').authRefresh()
        } catch {
          pb.authStore.clear()
        }
      }
      setLoading(false)
    })()
    return unsubscribe
  }, [])

  const login = async (email: string, password: string) => {
    await pb.collection('users').authWithPassword(email, password)
  }

  const register = async (email: string, password: string, name: string) => {
    await pb.collection('users').create({
      email,
      password,
      passwordConfirm: password,
      name,
    })
    await pb.collection('users').authWithPassword(email, password)
  }

  const logout = () => {
    pb.authStore.clear()
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: user !== null,
        isAdmin: user?.role === 'admin',
        loading,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
