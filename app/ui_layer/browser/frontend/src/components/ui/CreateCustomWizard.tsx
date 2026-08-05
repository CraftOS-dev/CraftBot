import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft, ArrowRight, Box, ChevronDown, Loader2, Paperclip,
  Sparkles, Upload, X,
} from 'lucide-react'
import { Button } from './Button'
import { LIVING_UI_ICONS } from './LivingUIIcon'
import { PRESET_THEMES, ThemeMiniPreview } from '../../pages/LivingUI/themeCatalog'
import styles from './CreateCustomWizard.module.css'

/**
 * Create Custom wizard — three steps inside the Add Living UI modal:
 *
 *   1. CONFIGURE  name/description, layout silhouette, theme, icon,
 *                 access mode, reference attachments
 *   2. INTERVIEW  LLM-generated questions (option chips + free text),
 *                 count scales with the app's complexity
 *   3. CREATING   requirements synthesis + project creation + build run;
 *                 on success the caller navigates to the new project
 *
 * The backend does the thinking (living_ui_wizard_interview /
 * living_ui_wizard_finalize); this component owns only the flow state.
 */

interface CreateCustomWizardProps {
  send: (type: string, data?: Record<string, unknown>) => void
  onMessage: (type: string, handler: (data: any) => void) => () => void
  onClose: () => void
  onCreated?: (projectId: string) => void
}

interface InterviewQuestion {
  id: string
  question: string
  why?: string
  multiSelect: boolean
  options: string[]
}

const MAX_WORDS = 5000

function countWords(text: string): number {
  const trimmed = text.trim()
  if (!trimmed) return 0
  return trimmed.split(/\s+/).length
}

// ── configure-step vocabulary ───────────────────────────────────────────────

const LAYOUTS: { id: string; label: string }[] = [
  { id: 'free', label: 'Free — agent decides' },
  { id: 'sidebar-body', label: 'Sidebar + body' },
  { id: 'topnav-body', label: 'Top nav + body' },
  { id: 'hero-cards', label: 'Hero + cards' },
  { id: 'split-view', label: 'Split view' },
  { id: 'dashboard', label: 'Dashboard grid' },
  { id: 'columns-board', label: 'Columns board' },
  { id: 'one-page', label: 'Single page' },
]

// Miniature layout silhouettes, drawn as SVG rect compositions.
function LayoutSilhouette({ id }: { id: string }) {
  const f = 'currentColor'
  const parts: Record<string, React.ReactNode> = {
    'sidebar-body': (
      <>
        <rect x="2" y="2" width="14" height="40" rx="2" fill={f} opacity="0.55" />
        <rect x="19" y="2" width="43" height="40" rx="2" fill={f} opacity="0.25" />
      </>
    ),
    'topnav-body': (
      <>
        <rect x="2" y="2" width="60" height="9" rx="2" fill={f} opacity="0.55" />
        <rect x="2" y="14" width="60" height="28" rx="2" fill={f} opacity="0.25" />
      </>
    ),
    'hero-cards': (
      <>
        <rect x="2" y="2" width="60" height="17" rx="2" fill={f} opacity="0.55" />
        <rect x="2" y="23" width="18" height="19" rx="2" fill={f} opacity="0.3" />
        <rect x="23" y="23" width="18" height="19" rx="2" fill={f} opacity="0.3" />
        <rect x="44" y="23" width="18" height="19" rx="2" fill={f} opacity="0.3" />
      </>
    ),
    'split-view': (
      <>
        <rect x="2" y="2" width="24" height="40" rx="2" fill={f} opacity="0.45" />
        <rect x="29" y="2" width="33" height="40" rx="2" fill={f} opacity="0.25" />
        <rect x="5" y="6" width="18" height="4" rx="1" fill={f} opacity="0.7" />
        <rect x="5" y="13" width="18" height="4" rx="1" fill={f} opacity="0.5" />
        <rect x="5" y="20" width="18" height="4" rx="1" fill={f} opacity="0.5" />
      </>
    ),
    dashboard: (
      <>
        <rect x="2" y="2" width="18" height="11" rx="2" fill={f} opacity="0.55" />
        <rect x="23" y="2" width="18" height="11" rx="2" fill={f} opacity="0.55" />
        <rect x="44" y="2" width="18" height="11" rx="2" fill={f} opacity="0.55" />
        <rect x="2" y="16" width="29" height="26" rx="2" fill={f} opacity="0.25" />
        <rect x="34" y="16" width="28" height="26" rx="2" fill={f} opacity="0.25" />
      </>
    ),
    'columns-board': (
      <>
        <rect x="2" y="2" width="18" height="40" rx="2" fill={f} opacity="0.35" />
        <rect x="23" y="2" width="18" height="40" rx="2" fill={f} opacity="0.35" />
        <rect x="44" y="2" width="18" height="40" rx="2" fill={f} opacity="0.35" />
        <rect x="5" y="6" width="12" height="7" rx="1" fill={f} opacity="0.75" />
        <rect x="26" y="6" width="12" height="7" rx="1" fill={f} opacity="0.75" />
        <rect x="26" y="16" width="12" height="7" rx="1" fill={f} opacity="0.6" />
      </>
    ),
    'one-page': (
      <rect x="12" y="2" width="40" height="40" rx="2" fill={f} opacity="0.4" />
    ),
    free: (
      <rect
        x="3" y="3" width="58" height="38" rx="3" fill="none" stroke={f}
        strokeOpacity="0.55" strokeWidth="2" strokeDasharray="5 4"
      />
    ),
  }
  return (
    <svg viewBox="0 0 64 44" className={styles.silhouetteSvg} aria-hidden="true">
      {parts[id] || parts.free}
    </svg>
  )
}

const ACCESS_CHOICES: { value: 'none' | 'multi-user'; label: string }[] = [
  { value: 'none', label: 'Just me (no login)' },
  { value: 'multi-user', label: 'Multi-user (accounts)' },
]

function newWizardId(): string {
  return `w_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

// ── component ───────────────────────────────────────────────────────────────

export function CreateCustomWizard({ send, onMessage, onClose, onCreated }: CreateCustomWizardProps) {
  const wizardIdRef = useRef(newWizardId())

  const [step, setStep] = useState<'configure' | 'interview' | 'creating'>('configure')

  // — configure state —
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [errors, setErrors] = useState<{ name?: string; description?: string }>({})
  const [layout, setLayout] = useState('free')
  const [uiTheme, setUiTheme] = useState('craftbot')
  const [authMode, setAuthMode] = useState<'none' | 'multi-user'>('none')
  const [iconChoice, setIconChoice] = useState<string | null>(null)
  const [iconFile, setIconFile] = useState<File | null>(null)
  const [iconPreview, setIconPreview] = useState<string | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [iconOpen, setIconOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  const wordCount = useMemo(() => countWords(description), [description])

  // — interview state —
  const [interviewLoading, setInterviewLoading] = useState(false)
  const [interviewError, setInterviewError] = useState<string | null>(null)
  const [questions, setQuestions] = useState<InterviewQuestion[]>([])
  const [qIndex, setQIndex] = useState(0)
  const [answers, setAnswers] = useState<Record<string, string[]>>({})
  const [freeText, setFreeText] = useState('')
  // True once the backend has run its one adapt follow-up round — sent back
  // on finalize so it never loops.
  const [followupDone, setFollowupDone] = useState(false)

  // — creating state —
  const [createError, setCreateError] = useState<string | null>(null)

  useEffect(() => {
    setTimeout(() => nameInputRef.current?.focus(), 100)
  }, [])

  useEffect(() => {
    const wid = wizardIdRef.current
    const cleanups = [
      onMessage('living_ui_wizard_interview', (data: any) => {
        if (data?.wizardId !== wid) return
        setInterviewLoading(false)
        if (data.success && Array.isArray(data.questions) && data.questions.length > 0) {
          setQuestions(data.questions)
          setQIndex(0)
          setInterviewError(null)
        } else {
          setInterviewError(data.error || 'Failed to prepare the interview')
        }
      }),
      onMessage('living_ui_wizard_finalize', (data: any) => {
        if (data?.wizardId !== wid) return
        if (data.success && Array.isArray(data.followupQuestions) && data.followupQuestions.length > 0) {
          // Second interview round (user chose "install & adapt"): the
          // backend wants to know WHAT to adapt. Finalize only fires after
          // the last question, so qIndex sits on it — append and step in.
          setFollowupDone(true)
          setQuestions(prev => [...prev, ...data.followupQuestions])
          setQIndex(i => i + 1)
          setStep('interview')
        } else if (data.success && data.projectId) {
          onCreated?.(data.projectId)
          onClose()
        } else {
          setCreateError(data.error || 'Failed to create the Living UI')
        }
      }),
    ]
    return () => cleanups.forEach(c => c())
  }, [onMessage, onClose, onCreated])

  // ── configure helpers ──────────────────────────────────────────────────

  const pickIconFile = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.png,.svg,.ico,.jpg,.jpeg,.webp'
    input.onchange = e => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      setIconFile(file)
      setIconChoice(null)
      setIconPreview(prev => {
        if (prev) URL.revokeObjectURL(prev)
        return URL.createObjectURL(file)
      })
    }
    input.click()
  }

  const addReferenceFiles = (list: FileList | File[]) => {
    const accepted = Array.from(list).filter(f => f.size > 0)
    if (accepted.length === 0) return
    setFiles(prev => {
      const names = new Set(prev.map(f => f.name))
      return [...prev, ...accepted.filter(f => !names.has(f.name))]
    })
  }

  const validate = (): boolean => {
    const next: { name?: string; description?: string } = {}
    if (!name.trim()) next.name = 'Name is required'
    else if (name.length > 50) next.name = 'Name must be 50 characters or less'
    if (!description.trim()) next.description = 'Description is required'
    else if (description.trim().length < 10) next.description = 'Please provide more detail (at least 10 characters)'
    else if (wordCount > MAX_WORDS) next.description = `Description exceeds ${MAX_WORDS} word limit`
    setErrors(next)
    return Object.keys(next).length === 0
  }

  const buildConfig = () => ({
    name: name.trim(),
    description: description.trim(),
    layout,
    uiTheme,
    // Every preset is a kit style pack; the backend stamps it at scaffold.
    stylePack: uiTheme,
    authMode,
    icon: iconFile ? null : iconChoice, // an uploaded icon wins server-side
    attachments: files.map(f => ({ name: f.name, kind: 'reference' })),
  })

  const uploadStaged = async (): Promise<boolean> => {
    const wid = wizardIdRef.current
    setUploading(true)
    setUploadError(null)
    try {
      const uploadOne = async (file: File, kind: 'reference' | 'icon') => {
        const form = new FormData()
        form.append('file', file)
        const params = new URLSearchParams({ wizardId: wid, kind })
        const resp = await fetch(`/api/living-ui/stage?${params}`, {
          method: 'POST',
          body: form,
        })
        const result = await resp.json().catch(() => ({}))
        if (!resp.ok || result.error) {
          throw new Error(result.error || `Upload failed: ${file.name}`)
        }
      }
      if (iconFile) await uploadOne(iconFile, 'icon')
      for (const f of files) await uploadOne(f, 'reference')
      return true
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err))
      return false
    } finally {
      setUploading(false)
    }
  }

  const handleNext = async () => {
    if (!validate()) return
    if (!(await uploadStaged())) return
    setStep('interview')
    setInterviewLoading(true)
    setInterviewError(null)
    send('living_ui_wizard_interview', {
      wizardId: wizardIdRef.current,
      config: buildConfig(),
    })
  }

  // ── interview helpers ──────────────────────────────────────────────────

  const finalize = (finalAnswers: Record<string, string[]>) => {
    setStep('creating')
    setCreateError(null)
    const answerList = questions
      .filter(q => (finalAnswers[q.id] || []).length > 0)
      .map(q => ({
        id: q.id,
        question: q.question,
        answer: (finalAnswers[q.id] || []).join(', '),
      }))
    send('living_ui_wizard_finalize', {
      wizardId: wizardIdRef.current,
      config: buildConfig(),
      answers: answerList,
      followupDone,
    })
  }

  const advance = (next: Record<string, string[]>) => {
    setAnswers(next)
    setFreeText('')
    if (qIndex + 1 < questions.length) setQIndex(qIndex + 1)
    else finalize(next)
  }

  const selectSingle = (value: string) => {
    const q = questions[qIndex]
    setAnswers({ ...answers, [q.id]: [value] })
  }

  const toggleMulti = (value: string) => {
    const q = questions[qIndex]
    const current = answers[q.id] || []
    const next = current.includes(value)
      ? current.filter(v => v !== value)
      : [...current, value]
    setAnswers({ ...answers, [q.id]: next })
  }

  // Continue: a typed answer joins (multi) or replaces (single) the
  // selection; otherwise the checked options carry the answer.
  const handleContinue = () => {
    const q = questions[qIndex]
    const text = freeText.trim()
    const selected = answers[q.id] || []
    let final: string[]
    if (text) final = q.multiSelect ? [...selected, text] : [text]
    else final = selected
    if (final.length === 0) return
    advance({ ...answers, [q.id]: final })
  }

  const question = questions[qIndex]
  const canContinue =
    !!question &&
    ((answers[question.id] || []).length > 0 || freeText.trim().length > 0)

  // ── render ──────────────────────────────────────────────────────────────

  if (step === 'creating') {
    return (
      <div className={styles.stateScreen}>
        {createError ? (
          <>
            <p className={styles.stateError}>{createError}</p>
            <div className={styles.stateActions}>
              <Button variant="secondary" onClick={() => setStep(questions.length > 0 ? 'interview' : 'configure')}>
                Back
              </Button>
              <Button variant="primary" onClick={() => finalize(answers)}>Retry</Button>
            </div>
          </>
        ) : (
          <>
            <Loader2 size={28} className={styles.spinner} />
            <p className={styles.stateTitle}>Writing the requirements & starting the build…</p>
            <p className={styles.stateSub}>
              Your answers are being turned into a complete specification. You'll be
              taken to the live build view in a moment.
            </p>
          </>
        )}
      </div>
    )
  }

  if (step === 'interview') {
    return (
      <div className={styles.wizardBody}>
        {interviewLoading ? (
          <div className={styles.stateScreen}>
            <Loader2 size={28} className={styles.spinner} />
            <p className={styles.stateTitle}>Preparing your interview…</p>
            <p className={styles.stateSub}>
              The agent is reading your configuration and deciding what it still
              needs to know.
            </p>
          </div>
        ) : interviewError ? (
          <div className={styles.stateScreen}>
            <p className={styles.stateError}>{interviewError}</p>
            <div className={styles.stateActions}>
              <Button variant="secondary" onClick={() => setStep('configure')}>Back</Button>
              <Button
                variant="secondary"
                onClick={() => finalize({})}
              >
                Skip interview
              </Button>
              <Button variant="primary" onClick={() => void handleNext()}>Retry</Button>
            </div>
          </div>
        ) : question ? (
          <div className={styles.interview}>
            <div className={styles.interviewHeader}>
              <button
                type="button"
                className={styles.backLink}
                onClick={() => {
                  if (qIndex > 0) setQIndex(qIndex - 1)
                  else setStep('configure')
                }}
              >
                <ArrowLeft size={13} /> Back
              </button>
              <span className={styles.interviewProgress}>
                Question {qIndex + 1} of {questions.length}
              </span>
              <button
                type="button"
                className={styles.skipLink}
                onClick={() => finalize(answers)}
              >
                Skip remaining
              </button>
            </div>
            <h3 className={styles.questionText}>{question.question}</h3>
            {question.why && <p className={styles.questionWhy}>{question.why}</p>}
            <div className={styles.optionList}>
              {question.options.map(opt => {
                const selected = (answers[question.id] || []).includes(opt)
                return (
                  <label
                    key={opt}
                    className={`${styles.optionRow} ${selected ? styles.optionRowActive : ''}`}
                  >
                    <input
                      type={question.multiSelect ? 'checkbox' : 'radio'}
                      name={`cw-q-${question.id}`}
                      className={styles.optionInput}
                      checked={selected}
                      onChange={() =>
                        question.multiSelect ? toggleMulti(opt) : selectSingle(opt)
                      }
                    />
                    <span>{opt}</span>
                  </label>
                )
              })}
            </div>
            <div className={styles.freeAnswerRow}>
              <input
                className={styles.input}
                placeholder={question.multiSelect
                  ? 'Add your own answer (optional)…'
                  : 'Or type your own answer…'}
                value={freeText}
                onChange={e => setFreeText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && canContinue) handleContinue() }}
              />
              <Button
                variant="primary"
                icon={<ArrowRight size={14} />}
                onClick={handleContinue}
                disabled={!canContinue}
              >
                Continue
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    )
  }

  // step === 'configure'
  return (
    <div className={styles.wizardScroll}>
      <div className={styles.configForm}>
        <div className={styles.configInner}>
        <div className={styles.formGroup}>
          <label htmlFor="cw-name" className={styles.label}>
            Project Name <span className={styles.required}>*</span>
          </label>
          <div className={styles.nameRow}>
            <div className={styles.iconDropdownWrap}>
              <button
                type="button"
                className={styles.iconSquare}
                onClick={() => setIconOpen(v => !v)}
                title="App icon — click to change or upload a favicon"
              >
                {iconPreview ? (
                  <img src={iconPreview} alt="icon" className={styles.iconPreview} />
                ) : iconChoice ? (
                  (() => {
                    const Cmp = LIVING_UI_ICONS[iconChoice.slice(7)]
                    return Cmp ? <Cmp size={16} /> : <Box size={16} />
                  })()
                ) : (
                  <Box size={16} />
                )}
                <ChevronDown size={11} className={styles.iconSquareChevron} />
              </button>
              {iconOpen && (
                <div className={styles.iconPanel}>
                  <button
                    type="button"
                    className={styles.iconUploadRow}
                    onClick={() => { pickIconFile(); setIconOpen(false) }}
                  >
                    <Upload size={13} /> Upload favicon (png, svg, ico…)
                  </button>
                  <div className={styles.iconGrid}>
                    {Object.entries(LIVING_UI_ICONS).map(([iconName, Cmp]) => {
                      const value = `lucide:${iconName}`
                      return (
                        <button
                          key={iconName}
                          type="button"
                          className={`${styles.iconCell} ${iconChoice === value ? styles.iconCellActive : ''}`}
                          onClick={() => {
                            setIconChoice(prev => (prev === value ? null : value))
                            setIconFile(null)
                            setIconPreview(prev => {
                              if (prev) URL.revokeObjectURL(prev)
                              return null
                            })
                            setIconOpen(false)
                          }}
                        >
                          <Cmp size={15} />
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
            <input
              ref={nameInputRef}
              id="cw-name"
              type="text"
              className={`${styles.input} ${errors.name ? styles.inputError : ''}`}
              placeholder="e.g., World News Dashboard"
              value={name}
              onChange={e => setName(e.target.value)}
              maxLength={50}
            />
          </div>
          {errors.name && <span className={styles.errorText}>{errors.name}</span>}
        </div>

        <div className={styles.formGroup}>
          <label htmlFor="cw-desc" className={styles.label}>
            What should this UI do? <span className={styles.required}>*</span>
          </label>
          <textarea
            id="cw-desc"
            className={`${styles.textarea} ${errors.description ? styles.inputError : ''}`}
            placeholder="Describe what you want the Living UI to display and do. Be specific about the data, workflows, and anything it must get right…"
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={6}
          />
          <div className={styles.fieldFooter}>
            <span className={`${styles.wordCount} ${wordCount > MAX_WORDS ? styles.wordCountError : ''}`}>
              {wordCount.toLocaleString()} / {MAX_WORDS.toLocaleString()} words
            </span>
          </div>
          {errors.description && <span className={styles.errorText}>{errors.description}</span>}
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>Reference files (optional)</label>
          <div
            className={styles.dropZone}
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'
              input.multiple = true
              input.accept = '.png,.jpg,.jpeg,.webp,.gif,.pdf,.md,.txt,.docx'
              input.onchange = e => {
                const list = (e.target as HTMLInputElement).files
                if (list) addReferenceFiles(list)
              }
              input.click()
            }}
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault()
              addReferenceFiles(e.dataTransfer.files)
            }}
          >
            <Paperclip size={16} className={styles.dropIcon} />
            <span>Drop design sketches, screenshots, or documents — or click to browse</span>
          </div>
          {files.length > 0 && (
            <div className={styles.fileList}>
              {files.map(f => (
                <span key={f.name} className={styles.fileChip}>
                  {f.name}
                  <button
                    type="button"
                    className={styles.fileRemove}
                    onClick={() => setFiles(prev => prev.filter(x => x.name !== f.name))}
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}
          {uploadError && <span className={styles.errorText}>{uploadError}</span>}
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>Layout</label>
          <div className={styles.layoutGrid}>
            {LAYOUTS.map(l => (
              <button
                key={l.id}
                type="button"
                className={`${styles.layoutCard} ${layout === l.id ? styles.layoutCardActive : ''}`}
                onClick={() => setLayout(l.id)}
              >
                <LayoutSilhouette id={l.id} />
                <span className={styles.layoutLabel}>{l.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>Theme</label>
          <div className={styles.themeGrid}>
            {PRESET_THEMES.map(t => (
              <button
                key={t.id}
                type="button"
                className={`${styles.themeCard} ${uiTheme === t.id ? styles.themeCardActive : ''}`}
                onClick={() => setUiTheme(t.id)}
                title={t.hint || t.label}
              >
                <ThemeMiniPreview style={t.id} swatches={t.swatches} />
                <span className={styles.layoutLabel}>{t.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>Access</label>
          <div className={styles.accessRow}>
            {ACCESS_CHOICES.map(choice => (
              <button
                key={choice.value}
                type="button"
                className={`${styles.chip} ${authMode === choice.value ? styles.chipActive : ''}`}
                onClick={() => setAuthMode(choice.value)}
              >
                {choice.label}
              </button>
            ))}
          </div>
        </div>
        </div>
      </div>

      <div className={styles.footer}>
        <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          type="button"
          icon={uploading ? <Loader2 size={16} className={styles.spinner} /> : <Sparkles size={16} />}
          onClick={() => void handleNext()}
          disabled={uploading}
        >
          {uploading ? 'Uploading…' : 'Next'}
        </Button>
      </div>
    </div>
  )
}
