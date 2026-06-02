import React from 'react'
import { FileText, Image, File, Download } from 'lucide-react'
import { IconButton } from './IconButton'
import type { Attachment } from '../../types'
import styles from './AttachmentDisplay.module.css'

interface AttachmentDisplayProps {
  attachments: Attachment[]
  onDownload?: (attachment: Attachment) => void
  onPreview?: (attachment: Attachment) => void
}

// Helper to format file size
function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

// Helper to determine if file is an image
function isImageType(type: string): boolean {
  return type.startsWith('image/')
}

// Helper to get file icon based on type
function getFileIcon(type: string): React.ReactNode {
  if (isImageType(type)) {
    return <Image size={20} />
  }
  if (type.includes('pdf') || type.includes('document') || type.includes('text')) {
    return <FileText size={20} />
  }
  return <File size={20} />
}

export function AttachmentDisplay({ attachments, onDownload, onPreview }: AttachmentDisplayProps) {
  if (!attachments || attachments.length === 0) {
    return null
  }

  return (
    <div className={styles.attachmentContainer}>
      {attachments.map((attachment, index) => {
        const previewable = !!onPreview
        const body = (
          <>
            <div className={styles.thumbnailWrapper}>
              {isImageType(attachment.type) ? (
                <img
                  src={attachment.url}
                  alt={attachment.name}
                  className={styles.thumbnail}
                  onError={(e) => {
                    const target = e.target as HTMLImageElement
                    target.style.display = 'none'
                    target.parentElement?.classList.add(styles.iconFallback)
                  }}
                />
              ) : (
                <div className={styles.fileIcon}>
                  {getFileIcon(attachment.type)}
                </div>
              )}
            </div>

            <div className={styles.fileInfo}>
              <span className={styles.fileName} title={attachment.name}>
                {attachment.name}
              </span>
              <span className={styles.fileSize}>
                {formatFileSize(attachment.size)}
              </span>
            </div>
          </>
        )

        return (
          <div key={index} className={styles.attachment}>
            {previewable ? (
              <button
                type="button"
                className={styles.previewTrigger}
                onClick={() => onPreview!(attachment)}
                title="Click to preview"
              >
                {body}
              </button>
            ) : (
              body
            )}

            <div className={styles.actions}>
              {onDownload && (
                <IconButton
                  icon={<Download size={14} />}
                  size="sm"
                  variant="ghost"
                  tooltip="Download"
                  onClick={() => onDownload(attachment)}
                />
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
