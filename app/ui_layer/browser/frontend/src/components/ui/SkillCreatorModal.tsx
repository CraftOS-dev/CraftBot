import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Loader2 } from 'lucide-react'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
import styles from './SkillCreatorModal.module.css'

export type SkillCreatorMode = 'create' | 'improve'

export interface SkillCreatorSubmit {
  mode: SkillCreatorMode
  skillName?: string
  targetSkill?: string
}

export interface SkillCreatorSuccessInfo {
  skillName: string
  mode: SkillCreatorMode
}

export interface SkillCreatorModalProps {
  isOpen: boolean
  sourceSkills: string[]
  reservedNames: Set<string>
  status: 'idle' | 'submitting' | 'success' | 'error'
  serverError: string | null
  successInfo: SkillCreatorSuccessInfo | null
  onClose: () => void
  onSubmit: (payload: SkillCreatorSubmit) => void
}

const NAME_PATTERN = /^[a-z][a-z0-9-]{1,63}$/

type Choice = { kind: 'create' } | { kind: 'improve'; skill: string }

function choiceKey(c: Choice): string {
  return c.kind === 'create' ? 'create' : `improve:${c.skill}`
}

export function SkillCreatorModal({
  isOpen,
  sourceSkills,
  reservedNames,
  status,
  serverError,
  successInfo,
  onClose,
  onSubmit,
}: SkillCreatorModalProps) {
  const submitting = status === 'submitting'
  const isSuccess = status === 'success'

  const choices = useMemo<Choice[]>(() => {
    const list: Choice[] = [{ kind: 'create' }]
    for (const s of sourceSkills) {
      list.push({ kind: 'improve', skill: s })
    }
    return list
  }, [sourceSkills])

  const [selectedKey, setSelectedKey] = useState<string>(choiceKey(choices[0]))
  const [skillName, setSkillName] = useState<string>('')

  // Reset the form ONLY on the closed→open transition, not on every
  // `choices` change. This keeps the form intact while submitting (when
  // the parent may re-render and pass a new `choices` reference).
  const wasOpenRef = useRef(false)
  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      setSelectedKey(choiceKey(choices[0]))
      setSkillName('')
    }
    wasOpenRef.current = isOpen
  }, [isOpen, choices])

  const selected = choices.find(c => choiceKey(c) === selectedKey) ?? choices[0]
  const isCreateMode = selected.kind === 'create'

  const validationError = useMemo<string | null>(() => {
    if (!isCreateMode) return null
    const trimmed = skillName.trim()
    if (!trimmed) return null
    if (!NAME_PATTERN.test(trimmed)) {
      return 'Use lowercase letters, digits, and hyphens. Must start with a letter, 2–64 chars.'
    }
    if (reservedNames.has(trimmed)) {
      return 'This name is reserved. Pick another.'
    }
    return null
  }, [isCreateMode, skillName, reservedNames])

  const canSubmit = !submitting && !isSuccess && (
    isCreateMode
      ? skillName.trim().length > 0 && !validationError
      : true
  )

  const handleSubmit = () => {
    if (!canSubmit) return
    if (selected.kind === 'create') {
      onSubmit({ mode: 'create', skillName: skillName.trim() })
    } else {
      onSubmit({ mode: 'improve', targetSkill: selected.skill })
    }
  }

  // ─────────────────────────── SUCCESS VIEW ───────────────────────────
  // After the backend acknowledges, the modal stays open showing a
  // confirmation. The actual workflow runs in the background; the user
  // dismisses the modal manually.
  if (isSuccess && successInfo) {
    const isCreate = successInfo.mode === 'create'
    const verbing = isCreate ? 'Creating' : 'Improving'
    return (
      <Modal isOpen={isOpen} onClose={onClose} title="Skill workflow started" size="sm">
        <ModalBody className={styles.body}>
          <div className={styles.successIcon}>
            <Check size={28} />
          </div>
          <p className={styles.successHeadline}>
            {verbing} <code>{successInfo.skillName}</code>…
          </p>
          <p className={styles.intro}>
            The agent is working on it now. You'll see progress in chat
            and the new task will appear in the task panel. Feel free to
            close this dialog.
          </p>
        </ModalBody>
        <ModalFooter>
          <Button variant="primary" onClick={onClose}>
            Close
          </Button>
        </ModalFooter>
      </Modal>
    )
  }

  // ──────────────────────────── FORM VIEW ────────────────────────────
  const showRadio = sourceSkills.length > 0

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Create skill from task"
      size="sm"
      closeDisabled={submitting}
    >
      <ModalBody className={styles.body}>
        <p className={styles.intro}>
          CraftBot will read this task's record and turn it into a reusable skill.
          The new (or edited) skill will be invocable on future tasks.
        </p>

        {showRadio && (
          <div className={styles.choiceGroup} role="radiogroup">
            {choices.map(c => {
              const key = choiceKey(c)
              const isSel = key === selectedKey
              const label = c.kind === 'create'
                ? 'Create a new skill'
                : `Improve "${c.skill}"`
              const hint = c.kind === 'create'
                ? 'Distil this task into a brand-new skill.'
                : 'Refine the existing skill using this task as evidence.'
              return (
                <label
                  key={key}
                  className={`${styles.choiceItem} ${isSel ? styles.choiceItemSelected : ''}`}
                >
                  <input
                    type="radio"
                    className={styles.choiceRadio}
                    name="skill-creator-choice"
                    checked={isSel}
                    onChange={() => setSelectedKey(key)}
                    disabled={submitting}
                  />
                  <span className={styles.choiceLabel}>
                    <strong>{label}</strong>
                    <span className={styles.choiceHint}>{hint}</span>
                  </span>
                </label>
              )
            })}
          </div>
        )}

        {isCreateMode && (
          <>
            <label className={styles.fieldLabel} htmlFor="skill-creator-name">
              New skill name
            </label>
            <input
              id="skill-creator-name"
              type="text"
              className={`${styles.fieldInput} ${validationError ? styles.fieldInputError : ''}`}
              placeholder="my-new-skill"
              value={skillName}
              onChange={e => setSkillName(e.target.value)}
              disabled={submitting}
              autoFocus
              onKeyDown={e => {
                if (e.key === 'Enter') handleSubmit()
              }}
            />
            {validationError ? (
              <p className={styles.fieldError}>{validationError}</p>
            ) : (
              <p className={styles.fieldHint}>
                Lowercase letters, digits, and hyphens. Example: <code>weekly-pr-summary</code>.
              </p>
            )}
          </>
        )}

        {submitting && (
          <p className={styles.submittingText}>
            <Loader2 size={14} className={styles.spinning} />
            {' '}Submitting — waiting for the agent to acknowledge…
          </p>
        )}

        {serverError && (
          <p className={styles.fieldError}>{serverError}</p>
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" onClick={onClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={handleSubmit}
          disabled={!canSubmit}
          loading={submitting}
        >
          {isCreateMode ? 'Create' : 'Improve'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
