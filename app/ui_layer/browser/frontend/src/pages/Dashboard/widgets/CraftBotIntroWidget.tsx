import { useState, useRef, useEffect } from 'react'
import { Cloud, Users, Github, Box, ChevronRight, ArrowLeft, ExternalLink, Compass } from 'lucide-react'
import { CraftBotMascot, useMascotState, getPose } from '@mascot'
import type { MascotState } from '@mascot'
import { Button } from '../../../components/ui'
import { useTour } from '../../../tour'
import styles from './widgets.module.css'

interface IntroCard {
  id: string
  variant: 'vision' | 'chips' | 'articles'
  categoryLabel: string
  title: string
  subtitle: string
  /* Short one-liner shown at the smallest (1x1) size instead of items */
  desc: string
  items: { label: string; tag?: string; href?: string }[]
  cta: { label: string; href: string }
  icon: typeof Cloud
}

/* Copy comes from craftbot.live and the CraftBot docs. Keep in sync. */
const CARDS: IntroCard[] = [
  {
    id: 'cloud',
    variant: 'vision',
    categoryLabel: 'CraftBot Live',
    title: 'CraftBot Live',
    subtitle: 'Your personal CraftBot, always online',
    desc: 'Your personal CraftBot, always online',
    items: [
      { label: 'No SSH' },
      { label: 'No Docker' },
      { label: 'Runs while you sleep' },
      { label: 'Reach it from any device' }
    ],
    cta: { label: 'Start free', href: 'https://craftbot.live' },
    icon: Cloud
  },
  {
    id: 'livingui',
    variant: 'chips',
    categoryLabel: 'Living UI',
    title: 'An agent that builds and operates its own software',
    subtitle: 'Ask for an app and the agent designs, codes, tests, and launches it inside its own interface.',
    desc: 'Ask for an app. The agent designs, codes, tests, and launches it.',
    items: [
      { label: 'Kanban board' },
      { label: 'CRM' },
      { label: 'Habit tracker' },
      { label: 'Community marketplace' }
    ],
    cta: { label: 'Browse the Living UI marketplace', href: 'https://craftos.net/marketplace' },
    icon: Box
  },
  {
    id: 'bundles',
    variant: 'chips',
    categoryLabel: 'Agent Bundles',
    title: '40+ prebuilt agent personas',
    subtitle: 'Import CEO, finance, and DevOps agents with one click. 120 ready-made playbooks cover common automations.',
    desc: 'CEO, finance, DevOps, and 40+ other personas. One click to import.',
    items: [
      { label: 'CEO agent' },
      { label: 'Finance agent' },
      { label: 'DevOps engineer' },
      { label: '120 playbooks' },
      { label: 'One-click import' }
    ],
    cta: { label: 'Get agent bundles', href: 'https://github.com/CraftOS-dev/craftbot-agent-bundles' },
    icon: Users
  },
  {
    id: 'community',
    variant: 'articles',
    categoryLabel: 'Open Source',
    title: 'One agent. Every kind of work.',
    subtitle: 'MIT-licensed and free to self-host. Active development, weekly improvements.',
    desc: 'MIT-licensed, self-hostable, built in the open.',
    items: [
      {
        label: 'CraftOS-dev/CraftBot',
        tag: 'GitHub',
        href: 'https://github.com/CraftOS-dev/CraftBot'
      },
      {
        label: 'Join the CraftBot community',
        tag: 'Discord',
        href: 'https://discord.gg/ZN9YHc37HG'
      },
      {
        label: 'Community-built Living UIs',
        tag: 'Market',
        href: 'https://craftos.net/marketplace'
      }
    ],
    cta: { label: 'Star on GitHub', href: 'https://github.com/CraftOS-dev/CraftBot' },
    icon: Github
  }
]

export function CraftBotIntroWidget() {
  const { startTour } = useTour()
  const mascotState = useMascotState()
  // This widget's mascot never sleeps: any state whose pose renders the
  // sleeping silhouette shows the awake 'resting' pose here instead. Scoped to
  // this widget only — the Mascot widget and chat mascot keep sleep behavior.
  const awakeMascotState: MascotState = getPose(mascotState.state).sleeping
    ? 'resting'
    : mascotState.state
  const containerRef = useRef<HTMLDivElement>(null)
  const bannerScrollRef = useRef<HTMLDivElement>(null)

  const [showDetails, setShowDetails] = useState(false)
  const [currentBannerIndex, setCurrentBannerIndex] = useState(0)
  const [isEnlarged, setIsEnlarged] = useState(false)
  const [isFourBlocks, setIsFourBlocks] = useState(false)
  const [isHovered, setIsHovered] = useState(false)

  const [reaction, setReaction] = useState<'happy' | null>(null)
  const [beacon, setBeacon] = useState(false)
  const [completedCount, setCompletedCount] = useState(0)
  const timerRef = useRef<number | null>(null)

  // Track widget dimensions for 1x1, 2x1/1x2, and 2x2 (4 blocks)
  useEffect(() => {
    const node = containerRef.current
    if (!node) return

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        setIsFourBlocks(width >= 400 && height >= 340)
        setIsEnlarged(width > 320 || height > 270)
      }
    })

    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  // Auto-advance slides every 4.5 seconds when open and not hovered
  useEffect(() => {
    if (!showDetails || isHovered) return

    const interval = setInterval(() => {
      setCurrentBannerIndex((prev) => {
        const nextIdx = (prev + 1) % CARDS.length
        scrollToIndex(nextIdx)
        return nextIdx
      })
    }, 4500)

    return () => clearInterval(interval)
  }, [showDetails, isHovered])

  const handleMascotClick = () => {
    setReaction('happy')
    setBeacon(true)
    setCompletedCount((prev) => prev + 1)

    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
    }

    timerRef.current = window.setTimeout(() => {
      setReaction(null)
      setBeacon(false)
    }, 1800)
  }

  const handleScroll = () => {
    if (!bannerScrollRef.current) return
    const { scrollLeft, clientWidth } = bannerScrollRef.current
    if (clientWidth > 0) {
      const idx = Math.round(scrollLeft / clientWidth)
      setCurrentBannerIndex(idx)
    }
  }

  const scrollToIndex = (index: number) => {
    if (!bannerScrollRef.current) return
    const width = bannerScrollRef.current.clientWidth
    bannerScrollRef.current.scrollTo({
      left: index * width,
      behavior: 'smooth'
    })
    setCurrentBannerIndex(index)
  }

  if (showDetails) {
    return (
      <div
        ref={containerRef}
        className={styles.introDetailsContainer}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        {/* Header Bar */}
        <div className={styles.introDetailsHeader}>
          <button
            className={styles.backButton}
            onClick={() => setShowDetails(false)}
            aria-label="Back to welcome view"
          >
            <ArrowLeft size={12} />
            <span>Back</span>
          </button>
        </div>

        {/* Hero Split Card Banner Showcase */}
        <div className={styles.heroBannerShowcase}>
          <div
            ref={bannerScrollRef}
            className={styles.bannerScrollContainer}
            onScroll={handleScroll}
          >
            {CARDS.map((card) => {
              const Icon = card.icon
              const showItems = isEnlarged || isFourBlocks

              return (
                <div
                  key={card.id}
                  className={`${styles.heroBannerCard} ${card.variant === 'vision' ? styles.visionCard : ''}`}
                >
                  <div className={styles.heroContentSide}>
                    {card.variant !== 'vision' && showItems && (
                      <span className={styles.cardEyebrow}>
                        <Icon size={12} />
                        {card.categoryLabel}
                      </span>
                    )}

                    <h3 className={styles.heroTitle}>
                      {card.variant === 'vision' && (
                        <img
                          src="/craftbot-favicon-32x32.png"
                          alt=""
                          className={styles.titleFavicon}
                        />
                      )}
                      {card.title}
                    </h3>
                    {showItems && <p className={styles.heroSubtitle}>{card.subtitle}</p>}

                    {card.variant === 'articles' && showItems ? (
                      <div className={styles.articleList}>
                        {card.items.slice(0, isFourBlocks ? 3 : 2).map((item) => (
                          <a
                            key={item.label}
                            href={item.href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={styles.articleRow}
                          >
                            <span className={styles.articleTag}>{item.tag}</span>
                            <span className={styles.articleTitle}>{item.label}</span>
                          </a>
                        ))}
                      </div>
                    ) : card.variant !== 'articles' && showItems ? (
                      <div className={styles.chipRow}>
                        {card.items.slice(0, isFourBlocks ? card.items.length : 5).map((item) => (
                          <span key={item.label} className={styles.chip}>
                            {item.label}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className={styles.heroSimpleDesc}>{card.desc}</p>
                    )}

                    <a
                      href={card.cta.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={styles.cardCta}
                    >
                      <span>{card.cta.label}</span>
                      <ChevronRight size={13} />
                    </a>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Footer Row: Indicator Dots + craftbot.live Link */}
        <div className={styles.heroFooterRow}>
          <div className={styles.heroDotsGroup}>
            {CARDS.map((card, idx) => (
              <button
                key={card.id}
                className={`${styles.heroDot} ${idx === currentBannerIndex ? styles.activeHeroDot : ''}`}
                onClick={() => scrollToIndex(idx)}
                aria-label={`Go to slide ${idx + 1}`}
              />
            ))}
          </div>

          <a
            href="https://craftbot.live"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.redirectLink}
          >
            <span>craftbot.live</span>
            <ExternalLink size={11} />
          </a>
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className={styles.compactSimpleContainer}>
      <div
        className={styles.compactMascotWrapper}
        onClick={handleMascotClick}
        role="button"
        tabIndex={0}
        title="Click CraftBot!"
      >
        <CraftBotMascot
          state={awakeMascotState}
          size={isFourBlocks ? 80 : isEnlarged ? 64 : 52}
          reaction={reaction}
          beacon={beacon}
          completedCount={completedCount}
        />
      </div>

      <div className={styles.compactSimpleContent}>
        <h4 className={styles.compactSimpleTitle}>Welcome to CraftBot</h4>
        <p className={styles.compactSimpleSubtitle}>
          One agent. Every kind of work.
        </p>
      </div>

      <Button
        variant="primary"
        size="sm"
        icon={<ChevronRight size={14} />}
        iconPosition="right"
        className={styles.compactLearnMoreBtn}
        onClick={() => setShowDetails(true)}
      >
        Learn More
      </Button>

      {/* Replay the first-run walkthrough. Hidden at the smallest widget size
          so it never crowds the mascot + Learn More stack. */}
      {isEnlarged && (
        <Button
          variant="ghost"
          size="sm"
          icon={<Compass size={14} />}
          onClick={() => startTour('core', { restart: true })}
          style={{ marginTop: 'var(--space-2)' }}
        >
          Take a tour
        </Button>
      )}
    </div>
  )
}
