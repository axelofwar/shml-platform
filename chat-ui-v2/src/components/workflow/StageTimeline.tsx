/**
 * StageTimeline - Visual timeline for ACE workflow stages
 *
 * Displays the workflow progression:
 * Generator → Tools → Reflector → Curator → Complete
 *
 * Features:
 * - Visual representation of each stage
 * - Status indicators (pending/running/complete/error)
 * - Duration display for completed stages
 * - Compact and full modes
 */

import { motion } from 'framer-motion'
import { ACEStage, useWorkflowStore, StageStatus } from '../../stores/workflowStore'
import { cn } from '../../lib/utils'
import {
  Sparkles,
  Wrench,
  Eye,
  BookOpen,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  ArrowRight,
  Image,
} from 'lucide-react'

// Stage configuration
const STAGE_CONFIG: Record<ACEStage, {
  label: string
  icon: React.ComponentType<{ className?: string }>
  description: string
  color: string
}> = {
  [ACEStage.IDLE]: {
    label: 'Idle',
    icon: Clock,
    description: 'Waiting for input',
    color: 'gray',
  },
  [ACEStage.VISION]: {
    label: 'Vision',
    icon: Image,
    description: 'Analyzing images (Qwen3-VL)',
    color: 'cyan',
  },
  [ACEStage.GENERATOR]: {
    label: 'Generator',
    icon: Sparkles,
    description: 'Planning approach & tools',
    color: 'blue',
  },
  [ACEStage.TOOLS]: {
    label: 'Tools',
    icon: Wrench,
    description: 'Executing tool calls',
    color: 'purple',
  },
  [ACEStage.REFLECTOR]: {
    label: 'Reflector',
    icon: Eye,
    description: 'Evaluating quality',
    color: 'amber',
  },
  [ACEStage.CURATOR]: {
    label: 'Curator',
    icon: BookOpen,
    description: 'Extracting lessons',
    color: 'green',
  },
  [ACEStage.COMPLETE]: {
    label: 'Complete',
    icon: CheckCircle2,
    description: 'Workflow finished',
    color: 'emerald',
  },
  [ACEStage.ERROR]: {
    label: 'Error',
    icon: XCircle,
    description: 'An error occurred',
    color: 'red',
  },
}

// Stage order for display
const STAGE_ORDER: ACEStage[] = [
  ACEStage.VISION,      // Multi-modal vision analysis first (if image attached)
  ACEStage.GENERATOR,
  ACEStage.TOOLS,
  ACEStage.REFLECTOR,
  ACEStage.CURATOR,
  ACEStage.COMPLETE,
]

interface StageNodeProps {
  stage: ACEStage
  status: StageStatus | undefined
  isActive: boolean
}

function StageNode({ stage, status, isActive }: StageNodeProps) {
  const config = STAGE_CONFIG[stage]
  const Icon = config.icon

  const getStatusColor = () => {
    if (status?.status === 'error') return 'border-red-500 bg-red-500/10'
    if (status?.status === 'completed') return 'border-green-500 bg-green-500/10'
    if (status?.status === 'running') return 'border-blue-500 bg-blue-500/10'
    return 'border-gray-500/30 bg-gray-500/5'
  }

  const getStatusIcon = () => {
    if (status?.status === 'error') return <XCircle className="w-3 h-3 text-red-500" />
    if (status?.status === 'completed') return <CheckCircle2 className="w-3 h-3 text-green-500" />
    if (status?.status === 'running') return <Loader2 className="w-3 h-3 text-blue-500 animate-spin" />
    return null
  }

  const formatDuration = (ms?: number) => {
    if (!ms) return null
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      className={cn(
        'px-4 py-3 rounded-lg border-2 shadow-sm min-w-[120px]',
        'bg-background transition-all duration-300',
        getStatusColor(),
        isActive && 'ring-2 ring-blue-500 ring-offset-2 ring-offset-background'
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className={cn('w-5 h-5', `text-${config.color}-500`)} />
        <span className="font-medium text-sm">{config.label}</span>
        {getStatusIcon()}
      </div>

      {status?.status === 'running' && status.thinking && (
        <motion.p
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="text-xs text-muted-foreground mt-1 truncate max-w-[150px]"
        >
          {status.thinking}
        </motion.p>
      )}

      {status?.duration_ms && (
        <p className="text-xs text-muted-foreground mt-1">
          {formatDuration(status.duration_ms)}
        </p>
      )}
    </motion.div>
  )
}

interface StageTimelineProps {
  className?: string
  compact?: boolean
}

export function StageTimeline({ className, compact = false }: StageTimelineProps) {
  const { currentStage, stages, isActive } = useWorkflowStore()

  if (compact) {
    // Compact inline view
    return (
      <div className={cn('flex items-center gap-2', className)}>
        {STAGE_ORDER.map((stage, index, arr) => {
          const config = STAGE_CONFIG[stage]
          const status = stages[stage]
          const Icon = config.icon
          const isCurrentStage = currentStage === stage && isActive

          return (
            <div key={stage} className="flex items-center gap-2">
              <div
                className={cn(
                  'flex items-center gap-1 px-2 py-1 rounded-md text-xs',
                  status?.status === 'completed' && 'bg-green-500/10 text-green-500',
                  status?.status === 'running' && 'bg-blue-500/10 text-blue-500',
                  status?.status === 'error' && 'bg-red-500/10 text-red-500',
                  (!status?.status || status?.status === 'pending') && 'bg-gray-500/10 text-gray-500',
                  isCurrentStage && 'ring-1 ring-blue-500'
                )}
              >
                <Icon className="w-3 h-3" />
                <span className="hidden sm:inline">{config.label}</span>
                {status?.status === 'running' && (
                  <Loader2 className="w-3 h-3 animate-spin" />
                )}
              </div>
              {index < arr.length - 1 && (
                <div className={cn(
                  'w-4 h-0.5',
                  status?.status === 'completed' ? 'bg-green-500' : 'bg-gray-500/30'
                )} />
              )}
            </div>
          )
        })}
      </div>
    )
  }

  // Full timeline view with nodes and connectors
  return (
    <div className={cn('w-full bg-background/50 rounded-lg border p-6', className)}>
      <div className="flex items-center justify-between gap-2 overflow-x-auto">
        {STAGE_ORDER.map((stage, index, arr) => {
          const status = stages[stage]
          const isCurrentStage = currentStage === stage && isActive

          return (
            <div key={stage} className="flex items-center gap-4 flex-shrink-0">
              <StageNode
                stage={stage}
                status={status}
                isActive={isCurrentStage}
              />

              {index < arr.length - 1 && (
                <div className="flex items-center">
                  <div
                    className={cn(
                      'w-8 h-0.5 transition-colors',
                      status?.status === 'completed' ? 'bg-green-500' : 'bg-gray-500/30'
                    )}
                  />
                  <ArrowRight
                    className={cn(
                      'w-4 h-4 -ml-1 transition-colors',
                      status?.status === 'completed' ? 'text-green-500' : 'text-gray-500/30'
                    )}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default StageTimeline
