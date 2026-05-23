import React, { useEffect, useMemo, useState } from 'react'
import { ExternalLink, File } from 'lucide-react'
import { Highlight, themes, type Language } from 'prism-react-renderer'
import { basename } from './parse'
import styles from './primitives.module.css'
import tasksStyles from '../TasksPage.module.css'

// ─────────────────────────────────────────────────────────────────────
// Section wrapper used by renderers. Reuses TasksPage's .actionSection /
// .ioLabel so the renderer's sections sit alongside ActionBlock's own
// Error section + expanded detail panel with consistent borders (the
// .actionSection + .actionSection adjacent-sibling rule kicks in).
// ─────────────────────────────────────────────────────────────────────

interface SectionProps {
  label?: string
  children: React.ReactNode
}

export function Section({ label, children }: SectionProps) {
  return (
    <div className={tasksStyles.actionSection}>
      {label && <div className={tasksStyles.ioLabel}>{label}</div>}
      {children}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// File path chip: shows the basename prominently; full path on hover via
// the title attribute. Clickable when an onOpen handler is supplied.
// ─────────────────────────────────────────────────────────────────────

interface FilePathChipProps {
  path: string
  onOpen?: (path: string) => void
  showFull?: boolean   // show full path instead of basename
}

export function FilePathChip({ path, onOpen, showFull }: FilePathChipProps) {
  const label = showFull ? path : basename(path)
  const interactive = !!onOpen
  return (
    <button
      type="button"
      className={`${styles.filePathChip} ${interactive ? '' : styles.nonInteractive}`}
      title={path}
      onClick={() => onOpen?.(path)}
      disabled={!interactive}
    >
      <File size={11} aria-hidden="true" />
      <span className={styles.filePathChipPath}>{label}</span>
    </button>
  )
}

// ─────────────────────────────────────────────────────────────────────
// URL chip: opens in a new tab.
// ─────────────────────────────────────────────────────────────────────

interface UrlChipProps {
  url: string
  label?: string
}

export function UrlChip({ url, label }: UrlChipProps) {
  return (
    <a
      className={styles.urlChip}
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={url}
    >
      <ExternalLink size={11} aria-hidden="true" />
      <span className={styles.urlChipText}>{label ?? url}</span>
    </a>
  )
}

// ─────────────────────────────────────────────────────────────────────
// CodeBlock: syntax-highlighted code via prism-react-renderer. Falls back
// to plain monospace when the language isn't recognised by Prism.
// ─────────────────────────────────────────────────────────────────────

// Prism recognises a fixed set of language ids. Map our looser ids onto
// Prism's vocabulary; anything unknown is rendered without highlighting.
const PRISM_LANG_MAP: Record<string, Language> = {
  python: 'python',
  py: 'python',
  javascript: 'javascript',
  js: 'javascript',
  typescript: 'typescript',
  ts: 'typescript',
  tsx: 'tsx',
  jsx: 'jsx',
  markdown: 'markdown',
  md: 'markdown',
  html: 'markup',
  xml: 'markup',
  css: 'css',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  bash: 'bash',
  sh: 'bash',
  shell: 'bash',
  sql: 'sql',
  go: 'go',
  rust: 'rust',
  rs: 'rust',
  ruby: 'ruby',
  rb: 'ruby',
  java: 'java',
  c: 'c',
  cpp: 'cpp',
}

interface CodeBlockProps {
  code: string
  lang?: string
}

export function CodeBlock({ code, lang }: CodeBlockProps) {
  const prismLang = lang ? PRISM_LANG_MAP[lang.toLowerCase()] : undefined

  // No recognised language → plain monospace block.
  if (!prismLang) {
    return (
      <div>
        {lang && (
          <div className={styles.codeBlockHeader}>
            <span className={styles.codeBlockLang}>{lang}</span>
          </div>
        )}
        <pre className={styles.codeBlock}>{code}</pre>
      </div>
    )
  }

  return (
    <div>
      <div className={styles.codeBlockHeader}>
        <span className={styles.codeBlockLang}>{lang}</span>
      </div>
      <Highlight code={code} language={prismLang} theme={themes.vsDark}>
        {({ className, style, tokens, getLineProps, getTokenProps }) => (
          <pre className={`${styles.codeBlock} ${className}`} style={style}>
            {tokens.map((line, i) => (
              <div key={i} {...getLineProps({ line })}>
                {line.map((token, j) => (
                  <span key={j} {...getTokenProps({ token })} />
                ))}
              </div>
            ))}
          </pre>
        )}
      </Highlight>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Terminal: stdout + (optional) stderr, dark bg.
// ─────────────────────────────────────────────────────────────────────

interface TerminalProps {
  stdout?: string
  stderr?: string
}

export function Terminal({ stdout, stderr }: TerminalProps) {
  const hasOut = !!(stdout && stdout.length > 0)
  const hasErr = !!(stderr && stderr.length > 0)
  if (!hasOut && !hasErr) {
    return <pre className={styles.terminal}><span className={styles.terminalDim}>(no output)</span></pre>
  }
  return (
    <pre className={styles.terminal}>
      {hasOut && <span>{stdout}</span>}
      {hasOut && hasErr && '\n'}
      {hasErr && <span className={styles.terminalStderr}>{stderr}</span>}
    </pre>
  )
}

// ─────────────────────────────────────────────────────────────────────
// ResultList / ResultCard for search-style outputs.
// ─────────────────────────────────────────────────────────────────────

interface ResultCardProps {
  title: string
  url?: string
  snippet?: string
  onClick?: () => void
}

export function ResultCard({ title, url, snippet, onClick }: ResultCardProps) {
  const content = (
    <>
      <div className={styles.resultTitle}>{title}</div>
      {url && <div className={styles.resultUrl}>{url}</div>}
      {snippet && <div className={styles.resultSnippet}>{snippet}</div>}
    </>
  )
  if (url) {
    return (
      <a className={styles.resultCard} href={url} target="_blank" rel="noopener noreferrer">
        {content}
      </a>
    )
  }
  return (
    <div className={styles.resultCard} onClick={onClick} role={onClick ? 'button' : undefined}>
      {content}
    </div>
  )
}

export function ResultList({ children }: { children: React.ReactNode }) {
  return <div className={styles.resultList}>{children}</div>
}

// ─────────────────────────────────────────────────────────────────────
// ImageThumbnail: click → fullscreen overlay (close on click or Esc).
// ─────────────────────────────────────────────────────────────────────

interface ImageThumbnailProps {
  src: string
  alt?: string
}

export function ImageThumbnail({ src, alt }: ImageThumbnailProps) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  return (
    <>
      <img
        className={styles.imageThumb}
        src={src}
        alt={alt ?? ''}
        onClick={() => setOpen(true)}
        loading="lazy"
      />
      {open && (
        <div className={styles.imageOverlay} onClick={() => setOpen(false)}>
          <img className={styles.imageOverlayImg} src={src} alt={alt ?? ''} />
        </div>
      )}
    </>
  )
}

export function ImageThumbnailRow({ srcs, alt }: { srcs: string[]; alt?: string }) {
  return (
    <div className={styles.imageThumbsRow}>
      {srcs.map((s, i) => <ImageThumbnail key={i} src={s} alt={alt} />)}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Meta pills: small status/info chips (status_code, exit_code, etc.).
// ─────────────────────────────────────────────────────────────────────

type PillVariant = 'default' | 'success' | 'error' | 'warn'

export function MetaPill({ children, variant = 'default' }: { children: React.ReactNode; variant?: PillVariant }) {
  const cls =
    variant === 'success' ? `${styles.metaPill} ${styles.metaPillSuccess}` :
    variant === 'error' ? `${styles.metaPill} ${styles.metaPillError}` :
    variant === 'warn' ? `${styles.metaPill} ${styles.metaPillWarn}` :
    styles.metaPill
  return <span className={cls}>{children}</span>
}

export function MetaRow({ children }: { children: React.ReactNode }) {
  return <div className={styles.metaRow}>{children}</div>
}

// ─────────────────────────────────────────────────────────────────────
// DiffView: minimal old/new diff rendered as added/removed lines, with
// a "..." separator between them. We're not running a real Myers diff
// here — stream_edit gives us the literal old_string / new_string pair,
// so showing them as a remove-block-then-add-block is honest about what
// the action replaces.
// ─────────────────────────────────────────────────────────────────────

interface DiffViewProps {
  oldText: string
  newText: string
}

export function DiffView({ oldText, newText }: DiffViewProps) {
  const oldLines = useMemo(() => oldText.split('\n'), [oldText])
  const newLines = useMemo(() => newText.split('\n'), [newText])
  return (
    <div className={styles.diffBlock}>
      {oldLines.map((line, i) => (
        <span key={`o${i}`} className={`${styles.diffLine} ${styles.diffLineRemoved}`}>{line || ' '}</span>
      ))}
      {newLines.map((line, i) => (
        <span key={`n${i}`} className={`${styles.diffLine} ${styles.diffLineAdded}`}>{line || ' '}</span>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Show-more toggle for long bodies (markdown previews etc.).
// ─────────────────────────────────────────────────────────────────────

interface CollapsibleProps {
  text: string
  collapsedLines?: number
}

export function Collapsible({ text, collapsedLines = 5 }: CollapsibleProps) {
  const [expanded, setExpanded] = useState(false)
  const lines = text.split('\n')
  const isLong = lines.length > collapsedLines
  const shown = expanded || !isLong ? text : lines.slice(0, collapsedLines).join('\n') + '\n…'

  return (
    <>
      <pre className={styles.codeBlock}>{shown}</pre>
      {isLong && (
        <button className={styles.expandToggle} onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : `Show all ${lines.length} lines`}
        </button>
      )}
    </>
  )
}

export function Pending({ label }: { label?: string }) {
  return <div className={styles.pendingPlaceholder}>{label ?? 'Waiting for result…'}</div>
}

// Re-export the styles object so renderer files in this folder can also use
// a few specific classes (e.g. .section) for ad-hoc layouts.
export { styles as primStyles }
