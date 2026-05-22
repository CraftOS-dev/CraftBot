import React, { useEffect, useState, useMemo, useImperativeHandle, forwardRef } from 'react'
import { useSettingsWebSocket } from '@/pages/Settings/useSettingsWebSocket';
import { ActivitySquare, Terminal } from 'lucide-react'
import styles from './SlashCommandAutocomplete.module.css';
import { useAppSelector } from '../../store/hooks';
import {
  selectSkillsHasLoaded,
  selectEnabledSkillNames,
} from '../../store/selectors/skillsSettings'
import {
  selectCommandNames,
  selectCommandsHasLoaded,
} from '../../store/selectors/commandsSettings'

// interface SkillConfig {
//   name: string
//   description: string
//   enabled: boolean
//   user_invocable: boolean
//   action_sets: string[]
//   source: string
// }

// interface CommandConfig {
//   name: string
//   description: string
// }

type ItemKind = 'command' | 'skill'

interface AutocompleteItem {
  name: string
  kind: ItemKind
}

export interface SlashCommandAutocompleteHandle {
  /**
   * Handle a Tab keypress from the parent input.
   * - When 1 item is visible: commits it via `onSelectItem` and returns true.
   * - When >1 items are visible: cycles the highlighted index and returns true.
   * - When no items are visible: returns false so the caller can do nothing / fall through.
   */
  handleTab: () => boolean
  isOpen: () => boolean
}

interface SlashCommandProps {
    input: string;
    onSelectItem: (name: string) => void;
}

export const SlashCommandAutocomplete = forwardRef<SlashCommandAutocompleteHandle, SlashCommandProps>(
  function SlashCommandAutocomplete({ input, onSelectItem }, ref) {
    const [selectedIndex, setSelectedIndex] = useState<number>(0);

    const skills = useAppSelector(selectEnabledSkillNames);
    const hasLoaded = useAppSelector(selectSkillsHasLoaded);
    const commands = useAppSelector(selectCommandNames);
    const commandsHasLoaded = useAppSelector(selectCommandsHasLoaded);
    const { send, isConnected } = useSettingsWebSocket()

  // Fetch only if no one else has loaded the data yet this session.
  useEffect(() => {
    if (!isConnected) return
    if (!hasLoaded) send('skill_list')
    if (!commandsHasLoaded) send('command_list')
    }, [isConnected, hasLoaded, commandsHasLoaded, send])

    const query = input[0] === '/' ? input.slice(1).toLowerCase() : null

    const { filteredCommands, filteredSkills, flatItems } = useMemo(() => {
        if (query === null) {
            return { filteredCommands: [], filteredSkills: [], flatItems: [] as AutocompleteItem[] }
        }
        const fc = commands.filter((item: string) => item.toLowerCase().includes(query))
        const fs = skills.filter((item: string) => item.toLowerCase().includes(query))
        const flat: AutocompleteItem[] = [
            ...fc.map<AutocompleteItem>((name: any) => ({ name, kind: 'command' })),
            ...fs.map<AutocompleteItem>((name: any) => ({ name, kind: 'skill' })),
        ]
        return { filteredCommands: fc, filteredSkills: fs, flatItems: flat }
    }, [query, commands, skills])

    // Reset / clamp the selected index whenever the visible list changes.
    useEffect(() => {
        if (flatItems.length === 0) {
            if (selectedIndex !== 0) setSelectedIndex(0)
            return
        }
        if (selectedIndex >= flatItems.length) {
            setSelectedIndex(0)
        }
    }, [flatItems.length, selectedIndex])

    useImperativeHandle(ref, () => ({
        handleTab: () => {
            if (flatItems.length === 0) return false
            if (flatItems.length === 1) {
                onSelectItem(flatItems[0].name)
                return true
            }
            setSelectedIndex(prev => (prev + 1) % flatItems.length)
            return true
        },
        isOpen: () => flatItems.length > 0,
    }), [flatItems, onSelectItem])

    if (flatItems.length === 0) return null

    let runningIndex = 0
    return (
        <div>
            <ul className={styles.autocomplete}>
                {filteredCommands.length > 0 && (
                    <>
                        <p className={styles.header}><Terminal size={12} />Commands</p>
                        {filteredCommands.map((item: string) => {
                            const idx = runningIndex++
                            const isSelected = idx === selectedIndex
                            return (
                                <li
                                    key={`cmd-${item}`}
                                    className={`${styles.item}${isSelected ? ` ${styles.itemSelected}` : ''}`}
                                    onClick={() => onSelectItem(item)}
                                    onMouseEnter={() => setSelectedIndex(idx)}
                                >/{item}</li>
                            )
                        })}
                    </>
                )}
                {filteredSkills.length > 0 && (
                    <>
                        <p className={styles.header}><ActivitySquare size={12} />Skills</p>
                        {filteredSkills.map((item: string) => {
                            const idx = runningIndex++
                            const isSelected = idx === selectedIndex
                            return (
                                <li
                                    key={`skill-${item}`}
                                    className={`${styles.item}${isSelected ? ` ${styles.itemSelected}` : ''}`}
                                    onClick={() => onSelectItem(item)}
                                    onMouseEnter={() => setSelectedIndex(idx)}
                                >/{item}</li>
                            )
                        })}
                    </>
                )}
            </ul>
        </div>
    );
})
