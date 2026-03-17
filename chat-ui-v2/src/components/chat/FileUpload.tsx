/**
 * FileUpload Component - Multimodal attachment support
 *
 * Features:
 * - Drag and drop zone
 * - Click to select files
 * - File type validation (images, PDFs, code files)
 * - Size limits with visual feedback
 * - Thumbnail preview for images
 * - Upload progress indicator
 *
 * Supported file types:
 * - Images: jpg, jpeg, png, gif, webp, svg
 * - Documents: pdf, txt, md, json
 * - Code: py, js, ts, tsx, jsx, html, css, yaml, yml
 */

import React, { useRef, useState, useCallback } from 'react'
import {
  Upload,
  X,
  File,
  FileImage,
  FileCode,
  FileText,
  AlertCircle,
  CheckCircle
} from 'lucide-react'
import { MessageAttachment } from '@/stores/chatStore'

// File type configurations
const FILE_TYPES = {
  image: {
    extensions: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'],
    mimeTypes: ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml'],
    icon: FileImage,
    maxSize: 10 * 1024 * 1024, // 10MB
  },
  document: {
    extensions: ['pdf', 'txt', 'md', 'json'],
    mimeTypes: ['application/pdf', 'text/plain', 'text/markdown', 'application/json'],
    icon: FileText,
    maxSize: 25 * 1024 * 1024, // 25MB
  },
  code: {
    extensions: ['py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css', 'yaml', 'yml', 'sh', 'bash'],
    mimeTypes: ['text/x-python', 'text/javascript', 'text/typescript', 'text/html', 'text/css', 'text/yaml'],
    icon: FileCode,
    maxSize: 5 * 1024 * 1024, // 5MB
  },
}

// All allowed extensions
const ALLOWED_EXTENSIONS = [
  ...FILE_TYPES.image.extensions,
  ...FILE_TYPES.document.extensions,
  ...FILE_TYPES.code.extensions,
]

interface FileUploadProps {
  onFilesSelected: (files: File[]) => void
  maxFiles?: number
  disabled?: boolean
  className?: string
}

interface FilePreview {
  file: File
  id: string
  type: 'image' | 'document' | 'code'
  preview?: string // Data URL for images
  error?: string
  progress: number // 0-100
  status: 'pending' | 'uploading' | 'complete' | 'error'
}

export const FileUpload: React.FC<FileUploadProps> = ({
  onFilesSelected,
  maxFiles = 5,
  disabled = false,
  className = '',
}) => {
  const [isDragging, setIsDragging] = useState(false)
  const [files, setFiles] = useState<FilePreview[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  // Determine file type from extension
  const getFileType = useCallback((file: File): 'image' | 'document' | 'code' | null => {
    const ext = file.name.split('.').pop()?.toLowerCase() || ''
    if (FILE_TYPES.image.extensions.includes(ext)) return 'image'
    if (FILE_TYPES.document.extensions.includes(ext)) return 'document'
    if (FILE_TYPES.code.extensions.includes(ext)) return 'code'
    return null
  }, [])

  // Validate file
  const validateFile = useCallback((file: File): string | null => {
    const ext = file.name.split('.').pop()?.toLowerCase() || ''

    // Check extension
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `File type .${ext} not supported`
    }

    // Check size
    const fileType = getFileType(file)
    if (fileType) {
      const config = FILE_TYPES[fileType]
      if (file.size > config.maxSize) {
        const maxMB = config.maxSize / (1024 * 1024)
        return `File too large (max ${maxMB}MB)`
      }
    }

    return null
  }, [getFileType])

  // Process selected files
  const processFiles = useCallback(async (selectedFiles: FileList | File[]) => {
    const fileArray = Array.from(selectedFiles)
    const remaining = maxFiles - files.length
    const filesToProcess = fileArray.slice(0, remaining)

    const newPreviews: FilePreview[] = []

    for (const file of filesToProcess) {
      const type = getFileType(file)
      const error = validateFile(file)

      const preview: FilePreview = {
        file,
        id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        type: type || 'document',
        error: error || undefined,
        progress: error ? 0 : 100, // Skip upload for now, mark complete
        status: error ? 'error' : 'complete',
      }

      // Generate preview for images
      if (type === 'image' && !error) {
        try {
          preview.preview = await generateImagePreview(file)
        } catch {
          // Preview generation failed, continue anyway
        }
      }

      newPreviews.push(preview)
    }

    setFiles(prev => [...prev, ...newPreviews])

    // Notify parent of valid files
    const validFiles = newPreviews
      .filter(p => !p.error)
      .map(p => p.file)

    if (validFiles.length > 0) {
      onFilesSelected(validFiles)
    }
  }, [files.length, maxFiles, getFileType, validateFile, onFilesSelected])

  // Generate image preview as data URL
  const generateImagePreview = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result as string)
      reader.onerror = reject
      reader.readAsDataURL(file)
    })
  }

  // Remove file from list
  const removeFile = useCallback((id: string) => {
    setFiles(prev => prev.filter(f => f.id !== id))
  }, [])

  // Handle drag events
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!disabled) {
      setIsDragging(true)
    }
  }, [disabled])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)

    if (!disabled && e.dataTransfer.files.length > 0) {
      processFiles(e.dataTransfer.files)
    }
  }, [disabled, processFiles])

  // Handle click to select
  const handleClick = useCallback(() => {
    if (!disabled) {
      inputRef.current?.click()
    }
  }, [disabled])

  // Handle file input change
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processFiles(e.target.files)
      e.target.value = '' // Reset for same file selection
    }
  }, [processFiles])

  // Format file size
  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  // Get icon for file type
  const FileIcon = (type: 'image' | 'document' | 'code') => {
    const Icon = FILE_TYPES[type].icon
    return <Icon className="w-5 h-5" />
  }

  return (
    <div className={className}>
      {/* Drop zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        className={`
          relative border-2 border-dashed rounded-lg p-6 text-center cursor-pointer
          transition-all duration-200
          ${isDragging
            ? 'border-primary bg-primary/5'
            : 'border-zinc-600 hover:border-zinc-500 hover:bg-zinc-800/50'
          }
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        `}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ALLOWED_EXTENSIONS.map(ext => `.${ext}`).join(',')}
          onChange={handleInputChange}
          className="hidden"
          disabled={disabled}
        />

        <Upload className={`w-8 h-8 mx-auto mb-3 ${isDragging ? 'text-primary' : 'text-zinc-500'}`} />

        <p className="text-sm text-zinc-400 mb-1">
          {isDragging
            ? 'Drop files here'
            : 'Drag & drop files or click to browse'
          }
        </p>

        <p className="text-xs text-zinc-500">
          Images, PDFs, code files up to 25MB • Max {maxFiles} files
        </p>
      </div>

      {/* File previews */}
      {files.length > 0 && (
        <div className="mt-3 space-y-2">
          {files.map((filePreview) => (
            <div
              key={filePreview.id}
              className={`
                flex items-center gap-3 p-2 rounded-lg border
                ${filePreview.error
                  ? 'border-red-500/50 bg-red-500/10'
                  : 'border-zinc-700 bg-zinc-800/50'
                }
              `}
            >
              {/* Thumbnail or icon */}
              <div className="flex-shrink-0 w-10 h-10 rounded overflow-hidden bg-zinc-700 flex items-center justify-center">
                {filePreview.preview ? (
                  <img
                    src={filePreview.preview}
                    alt={filePreview.file.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  FileIcon(filePreview.type)
                )}
              </div>

              {/* File info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm text-zinc-200 truncate">
                  {filePreview.file.name}
                </p>
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-zinc-500">
                    {formatSize(filePreview.file.size)}
                  </span>
                  {filePreview.error ? (
                    <span className="flex items-center gap-1 text-red-400">
                      <AlertCircle className="w-3 h-3" />
                      {filePreview.error}
                    </span>
                  ) : filePreview.status === 'complete' ? (
                    <span className="flex items-center gap-1 text-green-400">
                      <CheckCircle className="w-3 h-3" />
                      Ready
                    </span>
                  ) : (
                    <span className="text-zinc-400">
                      Uploading {filePreview.progress}%
                    </span>
                  )}
                </div>
              </div>

              {/* Remove button */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  removeFile(filePreview.id)
                }}
                className="p-1 hover:bg-zinc-600 rounded transition-colors"
              >
                <X className="w-4 h-4 text-zinc-400" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default FileUpload
