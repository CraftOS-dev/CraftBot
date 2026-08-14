import { useState, useRef, useEffect } from 'react'
import { Zap, Plug, Brain, Box, ChevronRight, ArrowLeft, ExternalLink } from 'lucide-react'
import { CraftBotMascot, useMascotState } from '@mascot'
import styles from './widgets.module.css'

interface BannerItem {
  id: string
  categoryLabel: string
  title: string
  subtitle: string
  simpleDesc: string
  extendedPoints: string[]
  fourBlockPoints: string[]
  icon: typeof Zap
}

const BANNERS: BannerItem[] = [
  {
    id: 'autonomous',
    categoryLabel: 'Autonomous',
    title: 'Autonomous Execution',
    subtitle: 'Self-directed AI development engine',
    simpleDesc: 'Solves coding tasks step-by-step, edits files, and tests code automatically.',
    extendedPoints: [
      'Solves multi-step coding tasks & feature workflows',
      'Edits, creates, and refactors project files automatically',
      'Runs automated tests & verifies error diagnostics'
    ],
    fourBlockPoints: [
      'Solves multi-step coding tasks & end-to-end feature workflows',
      'Edits, creates, and refactors workspace files automatically',
      'Executes unit tests & automatically verifies runtime diagnostics',
      'Traces stack traces to isolate and fix root causes directly',
      'Maintains strict control flow scoping & error resilience'
    ],
    icon: Zap
  },
  {
    id: 'mcp',
    categoryLabel: 'MCP Tools',
    title: 'MCP Tools & API Integration',
    subtitle: 'Extensible Model Context Protocol ecosystem',
    simpleDesc: 'Connects directly to databases, external services, web APIs, and tools.',
    extendedPoints: [
      'Connects to external services, databases & web APIs',
      'Integrates with Model Context Protocol (MCP) toolkits',
      'Executes terminal commands & verified workspace scripts'
    ],
    fourBlockPoints: [
      'Connects to external services, databases, and third-party APIs',
      'Integrates with Model Context Protocol (MCP) server toolkits',
      'Executes verified terminal shell commands & workspace scripts',
      'Fetches live web documentation & parses API payload schemas',
      'Handles async background tasks with status reporting'
    ],
    icon: Plug
  },
  {
    id: 'memory',
    categoryLabel: 'Smart Memory',
    title: 'Smart Context & Memory',
    subtitle: 'Long-term vector codebase intelligence',
    simpleDesc: 'Remembers your project structure and keeps chat sessions fast and smart.',
    extendedPoints: [
      'Maintains vector-indexed memory of your codebase',
      'Compresses chat context to keep responses lightning fast',
      'Optimizes token budgets for long development sessions'
    ],
    fourBlockPoints: [
      'Maintains vector-indexed embeddings of your codebase',
      'Compresses chat context history to keep responses lightning fast',
      'Optimizes token budgets for multi-hour development sessions',
      'Recalls past architectural decisions & file symbol dependencies',
      'Monitors token context windows to prevent truncation losses'
    ],
    icon: Brain
  },
  {
    id: 'livingui',
    categoryLabel: 'Living UI',
    title: 'Living UI & Micro-Apps',
    subtitle: 'On-demand interactive web generator',
    simpleDesc: 'Generates interactive web screens, live charts, and custom dashboard cards.',
    extendedPoints: [
      'Generates interactive web components on demand',
      'Displays real-time status dashboards & telemetry graphs',
      'Integrates with drag-and-drop widget layouts'
    ],
    fourBlockPoints: [
      'Generates interactive web components & micro-apps on demand',
      'Displays real-time status telemetry & dynamic analytics charts',
      'Integrates smoothly with drag-and-drop widget grid layouts',
      'Renders responsive glassmorphism UI widgets with live data',
      'Persists widget configuration state & layout grid preferences'
    ],
    icon: Box
  }
]

export function CraftBotIntroWidget() {
  const mascotState = useMascotState()
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
        const nextIdx = (prev + 1) % BANNERS.length
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

          <span className={styles.introDetailsTitle}>Explore CraftBot</span>
        </div>

        {/* Hero Split Card Banner Showcase */}
        <div className={styles.heroBannerShowcase}>
          <div
            ref={bannerScrollRef}
            className={styles.bannerScrollContainer}
            onScroll={handleScroll}
          >
            {BANNERS.map((banner) => {
              return (
                <div key={banner.id} className={styles.heroBannerCard}>
                  {/* Left Visual Side with Mascot */}
                  <div className={styles.heroVisualSide}>
                    <div className={styles.heroMascotBox} onClick={handleMascotClick}>
                      <CraftBotMascot
                        state={mascotState.state}
                        size={isFourBlocks ? 64 : isEnlarged ? 52 : 40}
                        reaction={reaction}
                        beacon={beacon}
                        completedCount={completedCount}
                      />
                    </div>
                  </div>

                  {/* Right Content Side */}
                  <div className={styles.heroContentSide}>
                    <h3 className={styles.heroTitle}>{banner.title}</h3>
                    <p className={styles.heroSubtitle}>{banner.subtitle}</p>

                    {isFourBlocks ? (
                      <ul className={styles.heroPointsList}>
                        {banner.fourBlockPoints.map((pt, pIdx) => (
                          <li key={pIdx}>
                            <span className={styles.heroBullet} />
                            <span>{pt}</span>
                          </li>
                        ))}
                      </ul>
                    ) : isEnlarged ? (
                      <ul className={styles.heroPointsList}>
                        {banner.extendedPoints.map((pt, pIdx) => (
                          <li key={pIdx}>
                            <span className={styles.heroBullet} />
                            <span>{pt}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className={styles.heroSimpleDesc}>{banner.simpleDesc}</p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Footer Row: Indicator Dots + craftbot.live Link */}
        <div className={styles.heroFooterRow}>
          <div className={styles.heroDotsGroup}>
            {BANNERS.map((banner, idx) => (
              <button
                key={banner.id}
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
          state={mascotState.state}
          size={isFourBlocks ? 80 : isEnlarged ? 64 : 52}
          reaction={reaction}
          beacon={beacon}
          completedCount={completedCount}
        />
      </div>

      <div className={styles.compactSimpleContent}>
        <h4 className={styles.compactSimpleTitle}>Welcome to CraftBot</h4>
        <p className={styles.compactSimpleSubtitle}>
          {isFourBlocks
            ? 'Your Autonomous AI Agent Workspace & Living UI Platform'
            : 'Autonomous Agent & Living UI Platform'}
        </p>
      </div>

      <button
        className={styles.compactLearnMoreBtn}
        onClick={() => setShowDetails(true)}
      >
        <span>Learn More</span>
        <ChevronRight size={14} />
      </button>
    </div>
  )
}
