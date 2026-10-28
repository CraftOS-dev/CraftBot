import { Fragment, useEffect, useRef, type ReactNode } from 'react'
import styles from './AutocompleteMenu.module.css'

export interface AutocompleteMenuGroup {
  key: string
  icon: ReactNode
  title: string
  items: { key: string; label: string }[]
}

interface AutocompleteMenuProps {
  /** Shown in order; a group without items is skipped. */
  groups: AutocompleteMenuGroup[]
  /** Index across every group's items, in display order. */
  selectedIndex: number
  onSelect(index: number): void
  onHover(index: number): void
  /** Makes the list a listbox with option ids `${id}-${index}`, for an
   *  input's aria-controls / aria-activedescendant. */
  id?: string
  label?: string
}

/**
 * The composer's suggestion list above the input: grouped rows under an icon
 * header. Shared by "/" commands and "@" references so both look the same.
 * Keyboard handling stays with each caller.
 */
export function AutocompleteMenu({ groups, selectedIndex, onSelect, onHover, id, label }: AutocompleteMenuProps) {
  const itemRefs = useRef<(HTMLLIElement | null)[]>([])

  useEffect(() => {
    itemRefs.current[selectedIndex]?.scrollIntoView({ block: 'nearest' })
  }, [selectedIndex])

  let runningIndex = 0
  return (
    <div>
      <ul id={id} role={id ? 'listbox' : undefined} aria-label={label} className={styles.autocomplete}>
        {groups.filter(group => group.items.length > 0).map(group => (
          <Fragment key={group.key}>
            <p className={styles.header} aria-hidden={id ? true : undefined}>{group.icon}{group.title}</p>
            {group.items.map(item => {
              const index = runningIndex++
              const isSelected = index === selectedIndex
              return (
                <li
                  key={item.key}
                  id={id ? `${id}-${index}` : undefined}
                  role={id ? 'option' : undefined}
                  aria-selected={id ? isSelected : undefined}
                  ref={el => { itemRefs.current[index] = el }}
                  className={`${styles.item}${isSelected ? ` ${styles.itemSelected}` : ''}`}
                  // Keep focus in the input: a blur would close the list
                  // before the click lands.
                  onMouseDown={event => event.preventDefault()}
                  onClick={() => onSelect(index)}
                  onMouseEnter={() => onHover(index)}
                >{item.label}</li>
              )
            })}
          </Fragment>
        ))}
      </ul>
    </div>
  )
}
