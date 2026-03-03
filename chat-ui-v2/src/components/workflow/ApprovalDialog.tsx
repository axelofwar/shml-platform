/**
 * ApprovalDialog - shadcn dialog for tool approval workflow
 *
 * Features:
 * - Tool details display
 * - Code preview for sandbox executions
 * - Risk level indicator
 * - Approve/Deny buttons with keyboard shortcuts
 */

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'
import { Button } from '../ui/button'
import { cn } from '../../lib/utils'
import { ApprovalRequest, useWorkflowStore } from '../../stores/workflowStore'
import {
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  CheckCircle2,
  XCircle,
  Terminal,
  FileCode,
  AlertTriangle,
  Clock,
  Code,
} from 'lucide-react'

// Risk level configuration
const RISK_CONFIG: Record<string, {
  icon: React.ComponentType<{ className?: string }>
  label: string
  color: string
  bgColor: string
  description: string
}> = {
  low: {
    icon: ShieldCheck,
    label: 'Low Risk',
    color: 'text-green-500',
    bgColor: 'bg-green-500/10',
    description: 'This operation is generally safe',
  },
  medium: {
    icon: ShieldQuestion,
    label: 'Medium Risk',
    color: 'text-yellow-500',
    bgColor: 'bg-yellow-500/10',
    description: 'Review the code carefully before approving',
  },
  high: {
    icon: ShieldAlert,
    label: 'High Risk',
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
    description: 'This operation may have significant side effects',
  },
}

interface ApprovalDialogProps {
  request: ApprovalRequest | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onApprove: (requestId: string) => void
  onReject: (requestId: string) => void
}

export function ApprovalDialog({
  request,
  open,
  onOpenChange,
  onApprove,
  onReject,
}: ApprovalDialogProps) {
  const [isApproving, setIsApproving] = useState(false)
  const [isRejecting, setIsRejecting] = useState(false)

  // Keyboard shortcuts
  useEffect(() => {
    if (!open || !request) return

    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd + Enter to approve
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault()
        handleApprove()
      }
      // Escape to reject (handled by dialog)
      // Ctrl/Cmd + Backspace to reject
      if ((e.metaKey || e.ctrlKey) && e.key === 'Backspace') {
        e.preventDefault()
        handleReject()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, request])

  if (!request) return null

  const riskConfig = RISK_CONFIG[request.risk_level] || RISK_CONFIG.medium
  const RiskIcon = riskConfig.icon

  const handleApprove = async () => {
    setIsApproving(true)
    try {
      await onApprove(request.id)
    } finally {
      setIsApproving(false)
    }
  }

  const handleReject = async () => {
    setIsRejecting(true)
    try {
      await onReject(request.id)
    } finally {
      setIsRejecting(false)
    }
  }

  const formatCode = () => {
    const args = request.arguments
    // Common patterns for code extraction
    if (args.code) return args.code
    if (args.script) return args.script
    if (args.command) return args.command
    if (args.query) return args.query
    // Fallback to JSON
    return JSON.stringify(args, null, 2)
  }

  const getLanguage = () => {
    const toolName = request.tool_name.toLowerCase()
    if (toolName.includes('python')) return 'python'
    if (toolName.includes('node') || toolName.includes('javascript')) return 'javascript'
    if (toolName.includes('bash') || toolName.includes('shell')) return 'bash'
    if (toolName.includes('sql')) return 'sql'
    return 'text'
  }

  const formatTimestamp = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleString()
    } catch {
      return timestamp
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Terminal className="w-5 h-5 text-purple-500" />
            Tool Approval Required
          </DialogTitle>
          <DialogDescription>
            The agent wants to execute a tool that requires your approval.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-4 py-4">
          {/* Risk Level Badge */}
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn(
              'flex items-center gap-3 p-3 rounded-lg border',
              riskConfig.bgColor,
              `border-${riskConfig.color.replace('text-', '')}/30`
            )}
          >
            <RiskIcon className={cn('w-6 h-6', riskConfig.color)} />
            <div>
              <h3 className={cn('font-medium', riskConfig.color)}>
                {riskConfig.label}
              </h3>
              <p className="text-sm text-muted-foreground">
                {riskConfig.description}
              </p>
            </div>
          </motion.div>

          {/* Tool Information */}
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Tool Name
              </label>
              <p className="font-mono text-sm bg-gray-100 dark:bg-gray-900 px-2 py-1 rounded mt-1">
                {request.tool_name}
              </p>
            </div>

            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Requested At
              </label>
              <p className="text-sm text-muted-foreground flex items-center gap-1 mt-1">
                <Clock className="w-3 h-3" />
                {formatTimestamp(request.requested_at)}
              </p>
            </div>

            {/* Reasoning */}
            {request.reasoning && (
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Agent's Reasoning
                </label>
                <p className="text-sm bg-blue-500/10 border border-blue-500/30 p-2 rounded mt-1">
                  {request.reasoning}
                </p>
              </div>
            )}

            {/* Code Preview */}
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1">
                <Code className="w-3 h-3" />
                Code to Execute ({getLanguage()})
              </label>
              <div className="relative mt-1">
                <pre className="text-xs bg-gray-900 text-gray-100 p-3 rounded-lg overflow-x-auto max-h-[200px]">
                  <code>{formatCode()}</code>
                </pre>
              </div>
            </div>

            {/* Warning for high risk */}
            {request.risk_level === 'high' && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg"
              >
                <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                <div className="text-sm">
                  <p className="font-medium text-red-500">Security Warning</p>
                  <p className="text-muted-foreground">
                    This operation has been flagged as high risk. Please carefully review
                    the code before approving. Consider the potential impact on your system.
                  </p>
                </div>
              </motion.div>
            )}
          </div>
        </div>

        <DialogFooter className="flex-shrink-0 gap-2 sm:gap-2">
          <div className="flex-1 text-xs text-muted-foreground hidden sm:block">
            <kbd className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 font-mono">
              ⌘+Enter
            </kbd>{' '}
            to approve,{' '}
            <kbd className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 font-mono">
              Esc
            </kbd>{' '}
            to cancel
          </div>

          <Button
            variant="outline"
            onClick={handleReject}
            disabled={isApproving || isRejecting}
            className="gap-2"
          >
            {isRejecting ? (
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 1, repeat: Infinity }}
              >
                <XCircle className="w-4 h-4" />
              </motion.div>
            ) : (
              <XCircle className="w-4 h-4" />
            )}
            Deny
          </Button>

          <Button
            onClick={handleApprove}
            disabled={isApproving || isRejecting}
            className={cn(
              'gap-2',
              request.risk_level === 'high' && 'bg-red-600 hover:bg-red-700'
            )}
          >
            {isApproving ? (
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 1, repeat: Infinity }}
              >
                <CheckCircle2 className="w-4 h-4" />
              </motion.div>
            ) : (
              <CheckCircle2 className="w-4 h-4" />
            )}
            {request.risk_level === 'high' ? 'Approve Anyway' : 'Approve'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default ApprovalDialog
