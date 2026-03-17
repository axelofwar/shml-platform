/**
 * AttachmentButton - Compact attachment trigger for chat input
 *
 * Integrates with FileUpload component via a popover
 * Shows selected file badges inline
 */

import React, { useState, useCallback } from 'react'
import { Paperclip, X, FileImage, FileText, FileCode, ChevronDown } from 'lucide-react'
import { FileUpload } from './FileUpload'

export interface AttachmentFile {
  id: string
  file: File
  type: 'image' | 'document' | 'code'
  preview?: string
}

interface AttachmentButtonProps {
  attachments: AttachmentFile[]
  onAttachmentsChange: (attachments: AttachmentFile[]) => void
  disabled?: boolean
  maxFiles?: number
}

export const AttachmentButton: React.FC<AttachmentButtonProps> = ({
  attachments,
  onAttachmentsChange,
  disabled = false,
  maxFiles = 5,
}) => {
  const [isOpen, setIsOpen] = useState(false)

  // Handle files selected from FileUpload
  const handleFilesSelected = useCallback((files: File[]) => {
    const newAttachments: AttachmentFile[] = files.map(file => {
      const ext = file.name.split('.').pop()?.toLowerCase() || ''
      let type: 'image' | 'document' | 'code' = 'document'

      if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) {
        type = 'image'
      } else if (['py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css', 'yaml', 'yml', 'sh'].includes(ext)) {
        type = 'code'
      }

      return {
        id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        file,
        type,
      }
    })

    onAttachmentsChange([...attachments, ...newAttachments])
    setIsOpen(false)
  }, [attachments, onAttachmentsChange])

  // Remove attachment
  const removeAttachment = useCallback((id: string) => {
    onAttachmentsChange(attachments.filter(a => a.id !== id))
  }, [attachments, onAttachmentsChange])

  // Get icon for type
  const getIcon = (type: 'image' | 'document' | 'code') => {
    switch (type) {
      case 'image': return <FileImage className="w-3 h-3" />
      case 'code': return <FileCode className="w-3 h-3" />
      default: return <FileText className="w-3 h-3" />
    }
  }

  return (
    <div className="relative">
      {/* Main button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={disabled}
        className={`
          p-2 rounded-lg transition-colors
          ${attachments.length > 0
            ? 'bg-primary/20 text-primary hover:bg-primary/30'
            : 'hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200'
          }
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        `}
        title={`Attach files (${attachments.length}/${maxFiles})`}
      >
        <Paperclip className="w-5 h-5" />
        {attachments.length > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-primary text-primary-foreground text-xs rounded-full flex items-center justify-center">
            {attachments.length}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />

          {/* Panel */}
          <div className="absolute bottom-full left-0 mb-2 w-80 z-50 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl p-3">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-zinc-200">
                Attachments ({attachments.length}/{maxFiles})
              </span>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1 hover:bg-zinc-700 rounded"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Current attachments */}
            {attachments.length > 0 && (
              <div className="mb-3 space-y-1">
                {attachments.map((attachment) => (
                  <div
                    key={attachment.id}
                    className="flex items-center gap-2 p-1.5 bg-zinc-800 rounded text-xs"
                  >
                    {getIcon(attachment.type)}
                    <span className="flex-1 truncate text-zinc-300">
                      {attachment.file.name}
                    </span>
                    <button
                      onClick={() => removeAttachment(attachment.id)}
                      className="p-0.5 hover:bg-zinc-600 rounded"
                    >
                      <X className="w-3 h-3 text-zinc-400" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* File upload zone */}
            {attachments.length < maxFiles && (
              <FileUpload
                onFilesSelected={handleFilesSelected}
                maxFiles={maxFiles - attachments.length}
                disabled={disabled}
              />
            )}
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Inline attachment badges - shows in chat input area
 */
interface AttachmentBadgesProps {
  attachments: AttachmentFile[]
  onRemove: (id: string) => void
}

export const AttachmentBadges: React.FC<AttachmentBadgesProps> = ({
  attachments,
  onRemove,
}) => {
  if (attachments.length === 0) return null

  const getIcon = (type: 'image' | 'document' | 'code') => {
    switch (type) {
      case 'image': return <FileImage className="w-3 h-3" />
      case 'code': return <FileCode className="w-3 h-3" />
      default: return <FileText className="w-3 h-3" />
    }
  }

  return (
    <div className="flex flex-wrap gap-1 px-3 py-2 border-t border-zinc-700">
      {attachments.map((attachment) => (
        <div
          key={attachment.id}
          className="flex items-center gap-1.5 px-2 py-1 bg-zinc-800 rounded-full text-xs text-zinc-300"
        >
          {getIcon(attachment.type)}
          <span className="max-w-[100px] truncate">{attachment.file.name}</span>
          <button
            onClick={() => onRemove(attachment.id)}
            className="p-0.5 hover:bg-zinc-600 rounded-full"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      ))}
    </div>
  )
}

export default AttachmentButton
