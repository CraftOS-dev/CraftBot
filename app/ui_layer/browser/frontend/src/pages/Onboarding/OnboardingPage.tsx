import React, { useEffect, useState, useCallback } from 'react'
import {
  Check,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  SkipForward,
  // Icons for MCP servers and Skills
  Folder,
  Search,
  Github,
  Globe,
  FileText,
  MessageSquare,
  Mail,
  Calendar,
  CheckSquare,
  Gem,
  FlaskConical,
  Pencil,
  ClipboardList,
  Cloud,
  Sheet,
  type LucideIcon,
} from 'lucide-react'
import { Button } from '../../components/ui'
import { useWebSocket } from '../../contexts/WebSocketContext'
import type { OnboardingStep, OnboardingStepOption } from '../../types'
import styles from './OnboardingPage.module.css'

// Icon mapping for dynamic rendering
const ICON_MAP: Record<string, LucideIcon> = {
  Folder,
  Search,
  Github,
  Globe,
  FileText,
  MessageSquare,
  Mail,
  Calendar,
  CheckSquare,
  Gem,
  FlaskConical,
  Pencil,
  ClipboardList,
  Cloud,
  Sheet,
}

const STEP_NAMES = ['Provider', 'API Key', 'Agent Name', 'MCP Servers', 'Skills']

export function OnboardingPage() {
  const {
    connected,
    onboardingStep,
    onboardingError,
    onboardingLoading,
    requestOnboardingStep,
    submitOnboardingStep,
    skipOnboardingStep,
    goBackOnboardingStep,
  } = useWebSocket()

  // Local form state
  const [selectedValue, setSelectedValue] = useState<string | string[]>('')
  const [textValue, setTextValue] = useState('')

  // Request first step when connected
  useEffect(() => {
    if (connected && !onboardingStep && !onboardingLoading) {
      requestOnboardingStep()
    }
  }, [connected, onboardingStep, onboardingLoading, requestOnboardingStep])

  // Reset local state when step changes
  useEffect(() => {
    if (onboardingStep) {
      // For multi-select steps, use array
      if (onboardingStep.name === 'mcp' || onboardingStep.name === 'skills') {
        setSelectedValue(Array.isArray(onboardingStep.default) ? onboardingStep.default : [])
      } else if (onboardingStep.options.length > 0) {
        // Single select - find default option
        const defaultOption = onboardingStep.options.find(opt => opt.default)
        setSelectedValue(defaultOption?.value || onboardingStep.options[0]?.value || '')
      } else {
        // Text input
        setSelectedValue('')
        setTextValue(typeof onboardingStep.default === 'string' ? onboardingStep.default : '')
      }
    }
  }, [onboardingStep])

  const handleOptionSelect = useCallback((value: string) => {
    if (!onboardingStep) return

    if (onboardingStep.name === 'mcp' || onboardingStep.name === 'skills') {
      // Multi-select toggle
      setSelectedValue(prev => {
        const arr = Array.isArray(prev) ? prev : []
        if (arr.includes(value)) {
          return arr.filter(v => v !== value)
        } else {
          return [...arr, value]
        }
      })
    } else {
      // Single select
      setSelectedValue(value)
    }
  }, [onboardingStep])

  const handleSubmit = useCallback(() => {
    if (!onboardingStep) return

    if (onboardingStep.options.length > 0) {
      // Option-based step
      submitOnboardingStep(selectedValue)
    } else {
      // Text input step
      submitOnboardingStep(textValue)
    }
  }, [onboardingStep, selectedValue, textValue, submitOnboardingStep])

  const handleSkip = useCallback(() => {
    skipOnboardingStep()
  }, [skipOnboardingStep])

  const handleBack = useCallback(() => {
    goBackOnboardingStep()
  }, [goBackOnboardingStep])

  const isMultiSelect = onboardingStep?.name === 'mcp' || onboardingStep?.name === 'skills'
  const isWideStep = isMultiSelect  // MCP and Skills need wider container
  const isLastStep = onboardingStep ? onboardingStep.index === onboardingStep.total - 1 : false

  // Check if submit is valid
  const canSubmit = (() => {
    if (!onboardingStep) return false
    if (onboardingLoading) return false

    if (onboardingStep.options.length > 0) {
      if (isMultiSelect) {
        // Multi-select: can always submit (empty array is valid)
        return true
      }
      // Single select: must have selection
      return !!selectedValue
    } else {
      // Text input: required steps need non-empty value
      if (onboardingStep.required) {
        return textValue.trim().length > 0
      }
      return true
    }
  })()

  // Render loading state
  if (!connected || (!onboardingStep && onboardingLoading)) {
    return (
      <div className={styles.container}>
        <div className={styles.content}>
          <div className={styles.loading}>
            <div className={styles.spinner} />
            <div className={styles.loadingText}>
              {!connected ? 'Connecting...' : 'Loading...'}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Render step content
  const renderStepForm = () => {
    if (!onboardingStep) return null

    // Option-based step (single or multi select)
    if (onboardingStep.options.length > 0) {
      return (
        <div className={styles.formGroup}>
          <div className={styles.optionsList}>
            {onboardingStep.options.map((option: OnboardingStepOption) => {
              const isSelected = isMultiSelect
                ? Array.isArray(selectedValue) && selectedValue.includes(option.value)
                : selectedValue === option.value

              return (
                <div
                  key={option.value}
                  className={`${styles.optionItem} ${isSelected ? styles.selected : ''}`}
                  onClick={() => handleOptionSelect(option.value)}
                >
                  <div className={isMultiSelect ? styles.optionCheckbox : styles.optionRadio}>
                    {isMultiSelect && isSelected && <Check size={12} />}
                  </div>
                  <div className={styles.optionContent}>
                    <div className={styles.optionLabel}>
                      {option.icon && ICON_MAP[option.icon] && (
                        <span className={styles.optionIcon}>
                          {React.createElement(ICON_MAP[option.icon], { size: 16 })}
                        </span>
                      )}
                      {option.label}
                      {option.requires_setup && (
                        <span className={styles.setupBadge}>Setup required</span>
                      )}
                    </div>
                    {option.description && (
                      <div className={styles.optionDescription}>{option.description}</div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )
    }

    // Text input step
    const isApiKey = onboardingStep.name === 'api_key'

    return (
      <div className={styles.formGroup}>
        <input
          type={isApiKey ? 'password' : 'text'}
          className={`${styles.textInput} ${onboardingError ? styles.error : ''}`}
          value={textValue}
          onChange={(e) => setTextValue(e.target.value)}
          placeholder={isApiKey ? 'Enter your API key' : 'Enter a name'}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter' && canSubmit) {
              handleSubmit()
            }
          }}
        />
        {isApiKey && (
          <div className={styles.inputHint}>
            Your API key is stored locally.
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={styles.container}>
      {/* Progress Bar */}
      <div className={styles.progressBar}>
        {STEP_NAMES.map((name, index) => {
          const currentIndex = onboardingStep?.index ?? 0
          const isActive = index === currentIndex
          const isCompleted = index < currentIndex

          return (
            <React.Fragment key={name}>
              <div className={styles.stepIndicator}>
                <div
                  className={`${styles.stepDot} ${isActive ? styles.active : ''} ${isCompleted ? styles.completed : ''}`}
                >
                  {isCompleted ? <Check size={14} /> : index + 1}
                </div>
                <span className={`${styles.stepLabel} ${isActive ? styles.active : ''}`}>
                  {name}
                </span>
              </div>
              {index < STEP_NAMES.length - 1 && (
                <div className={`${styles.stepConnector} ${isCompleted ? styles.completed : ''} ${index === currentIndex - 1 ? styles.active : ''}`} />
              )}
            </React.Fragment>
          )
        })}
      </div>

      {/* Main Content */}
      <div className={styles.content}>
        <div className={`${styles.card} ${isWideStep ? styles.wide : ''}`}>
          {onboardingStep && (
            <>
              <h2 className={styles.stepTitle}>
                {onboardingStep.title}
                {!onboardingStep.required && (
                  <span className={styles.optionalBadge}>Optional</span>
                )}
              </h2>
              <p className={styles.stepDescription}>{onboardingStep.description}</p>

              {/* Error Message */}
              {onboardingError && (
                <div className={styles.errorMessage}>
                  <AlertCircle size={16} />
                  {onboardingError}
                </div>
              )}

              {/* Step Form */}
              {renderStepForm()}

              {/* Navigation Buttons */}
              <div className={styles.buttons}>
                <div className={styles.buttonsLeft}>
                  {onboardingStep.index > 0 && (
                    <Button
                      variant="ghost"
                      onClick={handleBack}
                      disabled={onboardingLoading}
                      icon={<ChevronLeft size={16} />}
                    >
                      Back
                    </Button>
                  )}
                </div>
                <div className={styles.buttonsRight}>
                  {!onboardingStep.required && (
                    <Button
                      variant="secondary"
                      onClick={handleSkip}
                      disabled={onboardingLoading}
                      icon={<SkipForward size={16} />}
                    >
                      Skip
                    </Button>
                  )}
                  <Button
                    variant="primary"
                    onClick={handleSubmit}
                    disabled={!canSubmit}
                    loading={onboardingLoading}
                    icon={<ChevronRight size={16} />}
                    iconPosition="right"
                  >
                    {isLastStep ? 'Finish' : 'Next'}
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
