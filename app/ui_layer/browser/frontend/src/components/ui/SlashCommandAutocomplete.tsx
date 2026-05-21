import React, { useEffect, useState, createContext, useContext } from 'react'
import { useSettingsWebSocket } from '@/pages/Settings/useSettingsWebSocket';
import { ActivitySquare } from 'lucide-react'
import styles from './SlashCommandAutocomplete.module.css';

interface SkillConfig {
  name: string
  description: string
  enabled: boolean
  user_invocable: boolean
  action_sets: string[]
  source: string
}

interface SlashCommandProps {
    input: string;
}

export function SlashCommandAutocomplete({ input }: SlashCommandProps) {
    const [skills, setSkills] = useState<string[]>(['']);
    const [query, setQuery] = useState<string>('');

    const { send, onMessage, isConnected } = useSettingsWebSocket()
    useEffect(() => {
        if (!isConnected) return;

        const cleanup = onMessage('skill_list', (data: unknown) => {
            const d = data as { success: boolean; skills?: SkillConfig[]; total?: number; enabled?: number; error?: string }
            if (d.success && d.skills) {
                const userInvocable = d.skills.filter(s => s.enabled)
                console.log('[SlashCommandAutocomplete] user-invocable skills:', userInvocable)
                setSkills(userInvocable.map(s => s.name))
            }
        })

        send('skill_list')
        return cleanup
    }, [isConnected, send, onMessage])

    console.log(skills)
    if (input && input[0] === '/' && skills.filter(item => item.includes(input.slice(1))).length > 0) return (
        <div>
            <ul className={styles.autocomplete}>
                <p className={styles.header}><ActivitySquare size={12}></ActivitySquare>Skills</p>
                {skills.filter(item => item.includes(input.slice(1))).map((item, index) => (
                    <li key={index} className={styles.item}>/{item}</li>
                ))}
            </ul>
        </div>
    );
}