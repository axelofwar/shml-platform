/**
 * StageCard - Individual stage display with expandable content
 *
 * Features:
 * - Stage name, status icon, duration
 * - Progress indicator during execution
 * - Expandable content for stage details
 * - Copy button for stage output
 */

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '../../lib/utils'
import { ACEStage, StageStatus } from '../../stores/workflowStore'
import {
  Sparkles,
  Wrench,
  Eye,
  BookOpen,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
} from 'lucide-react'
import { Button } from '../ui/button'

// Stage configuration
const STAGE_CONFIG: Record<ACEStage, {
  label: string
  icon: React.ComponentType<{ className?: string }>
  description: string
  color: string
  bgColor: string
  borderColor: string
}> = {
  [ACEStage.IDLE]: {
    label: 'Idle',
    icon: Clock,
    description: 'Waiting for input',
    color: 'text-gray-500',
    bgColor: 'bg-gray-500/10',
    borderColor: 'border-gray-500/30',
  },
  [ACEStage.VISION]: {
    label: 'Vision',
    icon: Eye,
    description: 'Analyzing images and visual content',
    color: 'text-cyan-500',
    bgColor: 'bg-cyan-500/10',
    borderColor: 'border-cyan-500/30',
  },
  [ACEStage.GENERATOR]: {
    label: 'Generator',
    icon: Sparkles,
    description: 'Planning approach and selecting tools',
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500/30',
  },
  [ACEStage.TOOLS]: {
    label: 'Tool Execution',
    icon: Wrench,
    description: 'Running selected tools',
    color: 'text-purple-500',
    bgColor: 'bg-purple-500/10',
    borderColor: 'border-purple-500/30',
  },
  [ACEStage.REFLECTOR]: {
    label: 'Reflector',
    icon: Eye,
    description: 'Evaluating response quality against rubrics',
    color: 'text-amber-500',
    bgColor: 'bg-amber-500/10',
    borderColor: 'border-amber-500/30',
  },
  [ACEStage.CURATOR]: {
    label: 'Curator',
    icon: BookOpen,
    description: 'Extracting lessons and patterns',
    color: 'text-green-500',
    bgColor: 'bg-green-500/10',
    borderColor: 'border-green-500/30',
  },
  [ACEStage.COMPLETE]: {
    label: 'Complete',
    icon: CheckCircle2,
    description: 'Workflow finished successfully',
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-emerald-500/30',
  },
  [ACEStage.ERROR]: {
    label: 'Error',
    icon: XCircle,
    description: 'An error occurred during execution',
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/30',
  },
}

interface StageCardProps {
  stage: ACEStage
  status: StageStatus
  isActive?: boolean
  content?: string | null
  className?: string
}

export function StageCard({
  stage,
  status,
  isActive = false,
  content,
  className,
}: StageCardProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const config = STAGE_CONFIG[stage]
  const Icon = config.icon

  const formatDuration = (ms?: number) => {
    if (!ms) return null
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  const getStatusBadge = () => {
    switch (status.status) {
      case 'completed':
        return (
          <span className="flex items-center gap-1 text-xs text-green-500 bg-green-500/10 px-2 py-0.5 rounded-full">
            <CheckCircle2 className="w-3 h-3" />
            Complete
          </span>
        )
      case 'running':
        return (
          <span className="flex items-center gap-1 text-xs text-blue-500 bg-blue-500/10 px-2 py-0.5 rounded-full">
            <Loader2 className="w-3 h-3 animate-spin" />
            Running
          </span>
        )
      case 'error':
        return (
          <span className="flex items-center gap-1 text-xs text-red-500 bg-red-500/10 px-2 py-0.5 rounded-full">
            <XCircle className="w-3 h-3" />
            Error
          </span>
        )
      default:
        return (
          <span className="flex items-center gap-1 text-xs text-gray-500 bg-gray-500/10 px-2 py-0.5 rounded-full">
            <Clock className="w-3 h-3" />
            Pending
          </span>
        )
    }
  }

  const handleCopy = async () => {
    if (!content) return
    await navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'rounded-lg border-2 overflow-hidden transition-all duration-300',
        config.borderColor,
        isActive && 'ring-2 ring-blue-500 ring-offset-2 ring-offset-background',
        className
      )}
    >
      {/* Header */}
      <div
        className={cn(
          'flex items-center justify-between p-3 cursor-pointer',
          config.bgColor
        )}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <div className={cn('p-2 rounded-lg', config.bgColor)}>
            <Icon className={cn('w-5 h-5', config.color)} />
          </div>
          <div>
            <h3 className="font-medium text-sm">{config.label}</h3>
            <p className="text-xs text-muted-foreground">{config.description}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {getStatusBadge()}

          {status.duration_ms && (
            <span className="text-xs text-muted-foreground">
              {formatDuration(status.duration_ms)}
            </span>
          )}

          {(content || status.thinking || status.error) && (
            <Button variant="ghost" size="sm" className="p-1 h-auto">
              {isExpanded ? (
                <ChevronUp className="w-4 h-4" />
              ) : (
                <ChevronDown className="w-4 h-4" />
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Progress bar for running stage */}
      {status.status === 'running' && (
        <div className="h-1 bg-gray-200 dark:bg-gray-800">
          <motion.div
            className={cn('h-full', config.bgColor.replace('/10', ''))}
            initial={{ width: '0%' }}
            animate={{ width: '100%' }}
            transition={{ duration: 30, ease: 'linear' }}
          />
        </div>
      )}

      {/* Expandable content */}
      <AnimatePresence>
        {isExpanded && (content || status.thinking || status.error) && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="p-3 border-t border-gray-200 dark:border-gray-800 space-y-2">
              {/* Thinking/Progress text */}
              {status.thinking && status.status === 'running' && (
                <div className="text-sm text-muted-foreground">
                  <span className="font-medium">Thinking:</span>
                  <p className="mt-1 italic">{status.thinking}</p>
                </div>
              )}

              {/* Error message */}
              {status.error && (
                <div className="p-2 rounded bg-red-500/10 border border-red-500/30">
                  <p className="text-sm text-red-500">{status.error}</p>
                </div>
              )}

              {/* Stage content/output */}
              {content && (
                <div className="relative">
                  <pre className="text-xs bg-gray-900 text-gray-100 p-3 rounded-lg overflow-x-auto max-h-[200px]">
                    {content}
                  </pre>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="absolute top-2 right-2 p-1 h-auto bg-gray-800 hover:bg-gray-700"
                    onClick={(e: React.MouseEvent) => {
                      e.stopPropagation()
                      handleCopy()
                    }}
                  >
                    {copied ? (
                      <Check className="w-3 h-3 text-green-500" />
                    ) : (
                      <Copy className="w-3 h-3 text-gray-400" />
                    )}
                  </Button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

export default StageCard
