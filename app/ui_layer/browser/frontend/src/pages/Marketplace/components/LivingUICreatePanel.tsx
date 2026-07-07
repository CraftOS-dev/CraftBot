import React, { useMemo, useRef, useState } from 'react'
import { Sparkles } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import styles from '../Marketplace.module.css'

const MAX_WORDS = 5000

function countWords(text: string): number {
  const trimmed = text.trim()
  if (!trimmed) return 0
  return trimmed.split(/\s+/).length
}

/** "Create Custom" flow — the agent builds a Living UI from the description.
 *  Extracted from the old CreateLivingUIModal custom tab. */
export function LivingUICreatePanel() {
  const { createLivingUI } = useWebSocket()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [errors, setErrors] = useState<{ name?: string; description?: string }>({})
  const nameInputRef = useRef<HTMLInputElement>(null)
  const wordCount = useMemo(() => countWords(description), [description])

  const validate = (): boolean => {
    const newErrors: { name?: string; description?: string } = {}
    if (!name.trim()) newErrors.name = 'Name is required'
    else if (name.length > 50) newErrors.name = 'Name must be 50 characters or less'
    if (!description.trim()) newErrors.description = 'Description is required'
    else if (description.length < 10) newErrors.description = 'Please provide more detail (at least 10 characters)'
    else if (wordCount > MAX_WORDS) newErrors.description = `Description exceeds ${MAX_WORDS} word limit`
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    createLivingUI({ name: name.trim(), description: description.trim() })
    setName('')
    setDescription('')
    // The build spawns a sidebar tab — go back to chat so progress is visible there.
    navigate('/')
  }

  return (
    <div className={styles.panelWrap}>
    <form onSubmit={handleSubmit} className={styles.panelForm}>
      <div className={styles.formGroup}>
        <label htmlFor="living-ui-name" className={styles.label}>
          Project Name <span className={styles.required}>*</span>
        </label>
        <input
          ref={nameInputRef}
          id="living-ui-name"
          type="text"
          className={`${styles.input} ${errors.name ? styles.inputError : ''}`}
          placeholder="e.g., World News Dashboard"
          value={name}
          onChange={e => setName(e.target.value)}
          maxLength={50}
        />
        {errors.name && <span className={styles.errorText}>{errors.name}</span>}
      </div>

      <div className={styles.formGroup}>
        <label htmlFor="living-ui-description" className={styles.label}>
          What should this UI do? <span className={styles.required}>*</span>
        </label>
        <textarea
          id="living-ui-description"
          className={`${styles.textareaLarge} ${errors.description ? styles.inputError : ''}`}
          placeholder="Describe what you want the Living UI to display and do. Be specific about the data, layout, interactions, styling preferences, and any external APIs or data sources to use..."
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={12}
        />
        <div className={styles.descriptionFooter}>
          <span className={styles.hint}>
            The clearer and more detailed your requirements, the more accurate the Living UI will be.
          </span>
          <span className={`${styles.wordCount} ${wordCount > MAX_WORDS ? styles.wordCountError : ''}`}>
            {wordCount.toLocaleString()} / {MAX_WORDS.toLocaleString()} words
          </span>
        </div>
        {errors.description && <span className={styles.errorText}>{errors.description}</span>}
      </div>

      <div className={styles.panelActions}>
        <button className={styles.panelSubmit} type="submit">
          <Sparkles size={16} /> Create Living UI
        </button>
      </div>
    </form>
    </div>
  )
}
