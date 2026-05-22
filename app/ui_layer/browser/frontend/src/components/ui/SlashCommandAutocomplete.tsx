import React, { useEffect, useState } from 'react'
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
    onSelectSkill: (skill: string) => void;
}

export function SlashCommandAutocomplete({ input, onSelectSkill }: SlashCommandProps) {
    const [skills, setSkills] = useState<string[]>([]);

    const { send, onMessage, isConnected } = useSettingsWebSocket()
    useEffect(() => {
        if (!isConnected) return;

        const cleanup = onMessage('skill_list', (data: unknown) => {
            const d = data as { success: boolean; skills?: SkillConfig[]; total?: number; enabled?: number; error?: string }
            if (d.success && d.skills) {
                const userInvocable = d.skills.filter(s => s.enabled)
                setSkills(userInvocable.map(s => s.name))
            }
        })

        send('skill_list')
        return cleanup
    }, [isConnected, send, onMessage])

    const filteredSkills = input[0] === '/' ? skills.filter(item => item.includes(input.slice(1))) : []
    
    if (filteredSkills.length > 0) return (
        <div>
            <ul className={styles.autocomplete}>
                <p className={styles.header}><ActivitySquare size={12}></ActivitySquare>Skills</p>
                {filteredSkills.map((item, index) => (
                    <li key={index} className={styles.item} onClick={() => onSelectSkill(item)}>/{item}</li>
                ))}
            </ul>
        </div>
    );
}