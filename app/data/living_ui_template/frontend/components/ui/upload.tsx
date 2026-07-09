/**
 * File upload presets (SYSTEM-MANAGED — do not edit)
 *
 * Backed by the system file-storage routes — never hand-roll multipart code.
 *
 *   // Generic attachments (drop zone + browse):
 *   <FileUpload onUploaded={f => attachments.create({ taskId, fileUrl: f.url, name: f.name })} />
 *
 *   // An image field on a form (upload + preview), stores the file URL:
 *   <ImageInput label="Cover" value={coverUrl} onValue={setCoverUrl} />
 *
 * Store `file.url` (a string) in a schema string field; render images with
 * `fileUrl(url)` from services/data.
 */

import { useRef, useState } from 'react'
import { Upload, X } from 'lucide-react'
import { uploadFile, fileUrl, StoredFileMeta } from '../../services/data'
import { Spinner } from './index'

export interface FileUploadProps {
  /** Called with the stored file's metadata after a successful upload. */
  onUploaded: (file: StoredFileMeta) => void
  /** Accept filter, e.g. "image/*" or ".csv" (native input semantics). */
  accept?: string
  label?: string
}

export function FileUpload({ onUploaded, accept, label }: FileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)

  const handle = async (file: File | undefined | null) => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      onUploaded(await uploadFile(file))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className="flex flex-col gap-1">
      {label && <span className="text-ink text-sm font-medium">{label}</span>}
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
        }}
        onDragOver={e => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => {
          e.preventDefault()
          setDragOver(false)
          void handle(e.dataTransfer.files?.[0])
        }}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 'var(--space-2)',
          padding: 'var(--space-4)',
          border: `1px dashed ${dragOver ? 'var(--color-primary)' : 'var(--border-primary)'}`,
          borderRadius: 'var(--radius-md)',
          backgroundColor: dragOver ? 'var(--color-primary-subtle)' : 'var(--bg-secondary)',
          color: 'var(--text-secondary)',
          fontSize: 'var(--font-size-sm)',
          cursor: 'pointer',
          transition: 'var(--transition-fast)',
        }}
      >
        {busy ? <Spinner size={14} /> : <Upload size={14} />}
        {busy ? 'Uploading…' : 'Drop a file or click to browse'}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{ display: 'none' }}
        onChange={e => void handle(e.target.files?.[0])}
      />
      {error && (
        <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-error)' }}>
          {error}
        </span>
      )}
    </div>
  )
}

export interface ImageInputProps {
  /** Stored file URL (the `url` from upload) or null. */
  value: string | null
  onValue: (url: string | null) => void
  label?: string
  /** Preview height in px (default 120). */
  height?: number
}

export function ImageInput({ value, onValue, label, height = 120 }: ImageInputProps) {
  if (value) {
    return (
      <div className="flex flex-col gap-1">
        {label && <span className="text-ink text-sm font-medium">{label}</span>}
        <div style={{ position: 'relative', display: 'inline-block' }}>
          <img
            src={fileUrl(value)}
            alt={label ?? 'Uploaded image'}
            style={{
              maxHeight: height,
              maxWidth: '100%',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-primary)',
              display: 'block',
            }}
          />
          <button
            type="button"
            onClick={() => onValue(null)}
            aria-label="Remove image"
            style={{
              position: 'absolute',
              top: 4,
              right: 4,
              display: 'inline-flex',
              padding: 2,
              backgroundColor: 'var(--overlay-color)',
              border: 'none',
              borderRadius: 'var(--radius-full)',
              color: 'var(--color-white)',
              cursor: 'pointer',
            }}
          >
            <X size={12} />
          </button>
        </div>
      </div>
    )
  }
  return (
    <FileUpload label={label} accept="image/*" onUploaded={f => onValue(f.url)} />
  )
}
