import React from 'react'
import { FileText, Image, File, Download, FolderOpen, ExternalLink } from 'lucide-react'
import { IconButton } from './IconButton'
import type { Attachment } from '../../types'
import styles from './AttachmentDisplay.module.css'

interface AttachmentDisplayProps {
  attachments: Attachment[]
  onOpenFile?: (path: string) => void
  onOpenFolder?: (path: string) => void
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

export function AttachmentDisplay({ attachments, onOpenFile, onOpenFolder }: AttachmentDisplayProps) {
  if (!attachments || attachments.length === 0) {
    return null
  }

  return (
    <div className={styles.attachmentContainer}>
      {attachments.map((attachment, index) => (
        <div key={index} className={styles.attachment}>
          {/* Thumbnail or icon */}
          <div className={styles.thumbnailWrapper}>
            {isImageType(attachment.type) ? (
              <img
                src={attachment.url}
                alt={attachment.name}
                className={styles.thumbnail}
                onError={(e) => {
                  // If image fails to load, replace with icon
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

          {/* File info */}
          <div className={styles.fileInfo}>
            <span className={styles.fileName} title={attachment.name}>
              {attachment.name}
            </span>
            <span className={styles.fileSize}>
              {formatFileSize(attachment.size)}
            </span>
          </div>

          {/* Actions */}
          <div className={styles.actions}>
            {onOpenFile && (
              <IconButton
                icon={<ExternalLink size={14} />}
                size="sm"
                variant="ghost"
                tooltip="Open file"
                onClick={() => onOpenFile(attachment.path)}
              />
            )}
            {onOpenFolder && (
              <IconButton
                icon={<FolderOpen size={14} />}
                size="sm"
                variant="ghost"
                tooltip="Open folder"
                onClick={() => onOpenFolder(attachment.path)}
              />
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
