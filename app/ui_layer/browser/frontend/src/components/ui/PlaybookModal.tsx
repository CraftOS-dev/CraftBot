import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  ArrowLeft,
  BookOpen,
  Check,
  Layout,
  Loader2,
  Search,
  Server,
  Sparkles,
  UserCircle,
  Wrench,
  Zap,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from './Button'
import { Modal } from './Modal'
import { MarkdownContent } from './MarkdownContent'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { setPendingPrefill } from '../../store/slices/chatInputSlice'
import { selectEnabledSkillNames } from '../../store/selectors/skillsSettings'
import {
  selectPlaybooks,
  selectPlaybooksError,
  selectPlaybooksHasLoaded,
} from '../../store/selectors/playbooks'
import { resetPlaybooks, type Playbook } from '../../store/slices/playbooksSlice'
import { RESOURCES, resourceSync, useResource } from '../../store/resources'
import styles from './PlaybookModal.module.css'

export interface PlaybookModalProps {
  isOpen: boolean
  onClose: () => void
}

const DEFAULT_EMOJI = '📖'

export function PlaybookModal({ isOpen, onClose }: PlaybookModalProps) {
  const { t } = useTranslation(['components', 'common'])
  const dispatch = useAppDispatch()
  const enabledSkills = useAppSelector(selectEnabledSkillNames)

  // The catalogue lives in the store, so it is still there when the modal is
  // reopened or remounted; ResourceSync asks for it when it is missing or
  // went stale (first use, reconnect).
  const playbooks = useAppSelector(selectPlaybooks)
  const hasLoaded = useAppSelector(selectPlaybooksHasLoaded)
  const loadError = useAppSelector(selectPlaybooksError)
  useResource(isOpen ? RESOURCES.playbooks : null)
  const loading = isOpen && !hasLoaded
  const error = hasLoaded && loadError !== null
    ? (loadError || t('components:playbookModal.loadFailed'))
    : null

  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [tagsExpanded, setTagsExpanded] = useState(false)
  const [selectedPlaybook, setSelectedPlaybook] = useState<Playbook | null>(null)

  const TAG_COLLAPSE_LIMIT = 8

  // Reset search + detail view whenever the modal closes so reopening starts clean.
  useEffect(() => {
    if (!isOpen) {
      setSearchQuery('')
      setSelectedTags(new Set())
      setTagsExpanded(false)
      setSelectedPlaybook(null)
    }
  }, [isOpen])

  const allTags = useMemo(() => {
    const counts = new Map<string, number>()
    playbooks.forEach(p => p.tags?.forEach(t => counts.set(t, (counts.get(t) || 0) + 1)))
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([t]) => t)
  }, [playbooks])

  const filteredPlaybooks = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return playbooks.filter(p => {
      if (q) {
        const hay = `${p.name} ${p.description ?? ''} ${(p.tags || []).join(' ')} ${p.category ?? ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      if (selectedTags.size > 0) {
        const tags = p.tags || []
        if (!tags.some(t => selectedTags.has(t))) return false
      }
      return true
    })
  }, [playbooks, searchQuery, selectedTags])

  const toggleTag = useCallback((tag: string) => {
    setSelectedTags(prev => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }, [])

  const enabledSkillsSet = useMemo(() => new Set(enabledSkills), [enabledSkills])

  const handleUse = useCallback((playbook: Playbook) => {
    dispatch(setPendingPrefill(playbook.prompt))
    onClose()
  }, [dispatch, onClose])

  if (!isOpen) return null

  // Detail view -----------------------------------------------------------
  if (selectedPlaybook) {
    const wbw = selectedPlaybook.works_best_with || {}

    return (
      <Modal
        isOpen
        onClose={onClose}
        size="auto"
        title={
          <span className={styles.titleRow}>
            <BookOpen size={18} className={styles.titleIcon} />
            {t('components:playbookModal.detailTitle')}
          </span>
        }
      >
        <div className={styles.detailBody}>
          <button
            type="button"
            className={styles.backButton}
            onClick={() => setSelectedPlaybook(null)}
          >
            <ArrowLeft size={14} />
            {t('components:playbookModal.backToAll')}
          </button>

          <div className={styles.detailHeader}>
            <span className={styles.detailEmoji} aria-hidden="true">
              {selectedPlaybook.emoji || DEFAULT_EMOJI}
            </span>
            <div>
              <h2 className={styles.detailName}>{selectedPlaybook.name}</h2>
              {selectedPlaybook.category && (
                <div className={styles.detailCategory}>{selectedPlaybook.category}</div>
              )}
            </div>
          </div>

          {(wbw.agent_profile || (wbw.skills && wbw.skills.length) || (wbw.mcp_servers && wbw.mcp_servers.length) || (wbw.agent_app_apps && wbw.agent_app_apps.length)) && (
            <div className={styles.section}>
              <div className={styles.sectionLabel}>
                {t('components:playbookModal.worksBestWith')}
                <span
                  className={styles.sectionHint}
                  title={t('components:playbookModal.worksBestWithHint')}
                >
                  ?
                </span>
              </div>
              <div className={styles.chips}>
                {wbw.agent_profile && (
                  <span className={styles.chip} title={t('components:playbookModal.suggestedAgentProfile')}>
                    <UserCircle size={12} />
                    {wbw.agent_profile}
                  </span>
                )}
                {(wbw.skills || []).map(skill => {
                  const installed = enabledSkillsSet.has(skill)
                  return (
                    <span
                      key={`skill-${skill}`}
                      className={`${styles.chip} ${installed ? styles.chipInstalled : ''}`}
                      title={installed ? t('components:playbookModal.skillEnabled') : t('components:playbookModal.suggestedSkill')}
                    >
                      <Wrench size={12} />
                      {skill}
                      {installed && <Check size={10} className={styles.chipCheck} />}
                    </span>
                  )
                })}
                {(wbw.mcp_servers || []).map(mcp => (
                  <span key={`mcp-${mcp}`} className={styles.chip} title={t('components:playbookModal.suggestedMcp')}>
                    <Server size={12} />
                    {mcp}
                  </span>
                ))}
                {(wbw.agent_app_apps || []).map(app => (
                  <span key={`app-${app}`} className={styles.chip} title={t('components:playbookModal.suggestedApp')}>
                    <Layout size={12} />
                    {app}
                  </span>
                ))}
              </div>
            </div>
          )}

          {selectedPlaybook.description && (
            <div className={styles.section}>
              <div className={styles.sectionLabel}>{t('components:playbookModal.about')}</div>
              <MarkdownContent
                content={selectedPlaybook.description}
                className={styles.description}
              />
            </div>
          )}

          {selectedPlaybook.steps && selectedPlaybook.steps.length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionLabel}>{t('components:playbookModal.whatItWillDo')}</div>
              <ol className={styles.steps}>
                {selectedPlaybook.steps.map((step, idx) => (
                  <li key={idx} className={styles.step}>
                    {step}
                  </li>
                ))}
              </ol>
            </div>
          )}

          <div className={styles.section}>
            <div className={styles.sectionLabel}>{t('components:playbookModal.promptPreview')}</div>
            <pre className={styles.promptPreview}>{selectedPlaybook.prompt}</pre>
          </div>

          <div className={styles.detailFooter}>
            <Button variant="secondary" onClick={() => setSelectedPlaybook(null)}>
              {t('common:actions.back')}
            </Button>
            <Button
              icon={<Zap size={14} />}
              onClick={() => handleUse(selectedPlaybook)}
            >
              {t('components:playbookModal.useButton')}
            </Button>
          </div>
        </div>
      </Modal>
    )
  }

  // List view -------------------------------------------------------------
  return (
    <Modal
      isOpen
      onClose={onClose}
      size="auto"
      title={
        <span className={styles.titleRow}>
          <BookOpen size={18} className={styles.titleIcon} />
          {t('components:playbookModal.title')}
        </span>
      }
    >
      <div className={styles.listBody}>
        <div className={styles.toolbar}>
          <div className={styles.searchWrapper}>
            <Search size={14} className={styles.searchIcon} />
            <input
              className={styles.searchInput}
              placeholder={t('components:playbookModal.searchPlaceholder')}
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              autoFocus
            />
          </div>
          {allTags.length > 0 && (() => {
            const visibleTags = tagsExpanded ? allTags : allTags.slice(0, TAG_COLLAPSE_LIMIT)
            const hiddenCount = Math.max(0, allTags.length - TAG_COLLAPSE_LIMIT)
            return (
              <div className={styles.tagsRow}>
                <button
                  type="button"
                  className={`${styles.tagChip} ${selectedTags.size === 0 ? styles.tagChipActive : ''}`}
                  onClick={() => setSelectedTags(new Set())}
                >
                  {t('components:playbookModal.filterAll')}
                </button>
                {visibleTags.map(tag => (
                  <button
                    key={tag}
                    type="button"
                    className={`${styles.tagChip} ${selectedTags.has(tag) ? styles.tagChipActive : ''}`}
                    onClick={() => toggleTag(tag)}
                  >
                    {tag}
                  </button>
                ))}
                {hiddenCount > 0 && (
                  <button
                    type="button"
                    className={styles.tagChip}
                    onClick={() => setTagsExpanded(v => !v)}
                  >
                    {tagsExpanded ? t('common:actions.showLess') : t('components:playbookModal.moreCount', { count: hiddenCount })}
                  </button>
                )}
              </div>
            )
          })()}
        </div>

        <div className={styles.listContent}>
          {loading ? (
            <div className={styles.stateCenter}>
              <Loader2 size={24} className={styles.spinner} />
            </div>
          ) : error ? (
            <div className={styles.stateCenter}>
              <p className={styles.stateText}>{error}</p>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  dispatch(resetPlaybooks())
                  resourceSync.refresh(RESOURCES.playbooks)
                }}
              >
                {t('common:actions.retry')}
              </Button>
            </div>
          ) : playbooks.length === 0 ? (
            <div className={styles.stateCenter}>
              <Sparkles size={32} className={styles.stateIcon} />
              <p className={styles.stateText}>{t('components:playbookModal.emptyNone')}</p>
            </div>
          ) : filteredPlaybooks.length === 0 ? (
            <div className={styles.stateCenter}>
              <Search size={32} className={styles.stateIcon} />
              <p className={styles.stateText}>{t('components:playbookModal.emptyFiltered')}</p>
            </div>
          ) : (
            <div className={styles.grid}>
              {filteredPlaybooks.map(playbook => (
                <button
                  key={playbook.id}
                  type="button"
                  className={styles.card}
                  onClick={() => setSelectedPlaybook(playbook)}
                >
                  <div className={styles.cardTitleRow}>
                    <span className={styles.cardEmoji} aria-hidden="true">
                      {playbook.emoji || DEFAULT_EMOJI}
                    </span>
                    <span className={styles.cardName}>{playbook.name}</span>
                  </div>
                  {playbook.description && (
                    <p className={styles.cardDesc}>{playbook.description}</p>
                  )}
                  {playbook.tags && playbook.tags.length > 0 && (
                    <div className={styles.cardTags}>
                      {playbook.tags.slice(0, 4).map(tag => (
                        <span key={tag} className={styles.cardTag}>
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}
