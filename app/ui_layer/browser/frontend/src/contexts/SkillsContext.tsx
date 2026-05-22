import { createContext, useContext, useEffect, useState } from 'react'
import { useSettingsWebSocket } from '@/pages/Settings/useSettingsWebSocket'

export interface SkillConfig {
  name: string
  description: string
  enabled: boolean
  user_invocable: boolean
  action_sets: string[]
  source: string
}

interface SkillsContextValue {
  skills: string[]
}

const SkillsContext = createContext<SkillsContextValue>({ skills: [] })

export function SkillsProvider({ children }: { children: React.ReactNode }) {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const [skills, setSkills] = useState<string[]>([])

  useEffect(() => {
    if (!isConnected) return

    const cleanup = onMessage('skill_list', (data: unknown) => {
      const d = data as { success: boolean; skills?: SkillConfig[]; error?: string }
      if (d.success && d.skills) {
        setSkills(d.skills.filter(s => s.user_invocable).map(s => s.name))
      }
    })

    send('skill_list')
    return cleanup
  }, [isConnected, send, onMessage])

  return <SkillsContext.Provider value={{ skills }}>{children}</SkillsContext.Provider>
}

export function useSkills() {
  return useContext(SkillsContext)
}
