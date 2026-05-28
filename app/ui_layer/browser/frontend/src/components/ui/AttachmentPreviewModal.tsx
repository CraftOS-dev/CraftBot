import { useEffect, useMemo, useState } from 'react'
import { Modal } from './Modal'
import styles from './AttachmentPreviewModal.module.css'

// A single shape that covers both pre-send attachments (base64 in memory)
// and sent attachments stored on the server (fetched by URL).
export interface AttachmentPreviewItem {
  name: string
  type: string
  size: number
  content?: string  // base64 — preferred when available
  url?: string      // backend URL — used when content is not provided
}

export interface AttachmentPreviewModalProps {
  isOpen: boolean
  attachment: AttachmentPreviewItem | null
  onClose: () => void
}

const TEXT_MIMES = new Set([
  'application/json', 'application/xml', 'application/javascript',
  'application/typescript', 'application/yaml', 'application/toml',
  'application/csv', 'application/x-sh',
])
const TEXT_EXT_RE = /\.(txt|md|csv|json|xml|yaml|yml|toml|sh|py|js|ts|jsx|tsx|css|html|htm|env|log|ini|cfg|conf)$/i

function classify(att: AttachmentPreviewItem) {
  const isImage = att.type.startsWith('image/')
  const isPdf = att.type === 'application/pdf' || att.name.toLowerCase().endsWith('.pdf')
  const isText = !isImage && !isPdf && (
    att.type.startsWith('text/')
    || TEXT_MIMES.has(att.type)
    || TEXT_EXT_RE.test(att.name)
  )
  return { isImage, isPdf, isText }
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

export function AttachmentPreviewModal({ isOpen, attachment, onClose }: AttachmentPreviewModalProps) {
  const kind = attachment ? classify(attachment) : null

  const imageSrc = useMemo(() => {
    if (!attachment || !kind?.isImage) return null
    if (attachment.content) return `data:${attachment.type};base64,${attachment.content}`
    return attachment.url ?? null
  }, [attachment, kind])

  // PDFs from base64 need a Blob URL so the iframe can load them; PDFs from
  // a backend URL can be loaded directly by the browser's PDF viewer.
  const pdfBlobUrl = useMemo(() => {
    if (!attachment || !kind?.isPdf || !attachment.content) return null
    try {
      const bytes = Uint8Array.from(atob(attachment.content), c => c.charCodeAt(0))
      return URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }))
    } catch {
      return null
    }
  }, [attachment, kind])

  useEffect(() => {
    return () => { if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl) }
  }, [pdfBlobUrl])

  const pdfSrc = pdfBlobUrl || (kind?.isPdf ? (attachment?.url ?? null) : null)

  const [textContent, setTextContent] = useState<string | null>(null)
  const [textLoading, setTextLoading] = useState(false)
  const [textError, setTextError] = useState<string | null>(null)

  useEffect(() => {
    if (!attachment || !kind?.isText) {
      setTextContent(null)
      setTextLoading(false)
      setTextError(null)
      return
    }
    if (attachment.content) {
      try {
        const bytes = Uint8Array.from(atob(attachment.content), c => c.charCodeAt(0))
        setTextContent(new TextDecoder('utf-8').decode(bytes))
        setTextError(null)
      } catch {
        setTextContent(null)
        setTextError('Failed to decode file.')
      }
      setTextLoading(false)
      return
    }
    if (attachment.url) {
      const ctrl = new AbortController()
      setTextLoading(true)
      setTextError(null)
      setTextContent(null)
      fetch(attachment.url, { signal: ctrl.signal })
        .then(r => {
          if (!r.ok) throw new Error(`Server returned ${r.status}`)
          return r.text()
        })
        .then(t => { setTextContent(t); setTextLoading(false) })
        .catch(err => {
          if (err.name === 'AbortError') return
          setTextError(`Failed to load file: ${err.message}`)
          setTextLoading(false)
        })
      return () => ctrl.abort()
    }
  }, [attachment, kind])

  if (!attachment || !kind) {
    return null
  }

  const lineCount = textContent ? textContent.split('\n').length : 0
  const meta = (
    <>
      {formatFileSize(attachment.size)}
      {kind.isText && lineCount > 0 && <> · {lineCount} line{lineCount !== 1 ? 's' : ''}</>}
    </>
  )

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={attachment.name}
      size="auto"
      contentClassName={styles.modal}
    >
      <div className={styles.metaBar}>{meta}</div>
      <div className={styles.viewer}>
        {kind.isImage && imageSrc && (
          <img src={imageSrc} alt={attachment.name} className={styles.image} />
        )}
        {kind.isPdf && pdfSrc && (
          <iframe src={pdfSrc} className={styles.pdf} title={attachment.name} />
        )}
        {kind.isText && (
          textLoading ? (
            <div className={styles.message}>Loading…</div>
          ) : textError ? (
            <div className={styles.message}>{textError}</div>
          ) : textContent != null ? (
            <pre className={styles.text}>{textContent}</pre>
          ) : null
        )}
        {!kind.isImage && !kind.isPdf && !kind.isText && (
          <div className={styles.message}>
            Preview isn't available for {attachment.name} ({formatFileSize(attachment.size)}).
          </div>
        )}
      </div>
    </Modal>
  )
}
