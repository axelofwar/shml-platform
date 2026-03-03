/**
 * ToolExecutionDrawer - Vaul drawer for tool execution details
 *
 * Features:
 * - Mobile-friendly drawer (slides up from bottom)
 * - Tool list with status badges
 * - Execution logs and output
 * - Expandable result preview
 */

import { useState } from 'react'
import { Drawer } from 'vaul'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '../../lib/utils'
import { ToolExecution, useWorkflowStore } from '../../stores/workflowStore'
import {
  Wrench,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  Terminal,
  FileCode,
  Search,
  GitBranch,
  Play,
} from 'lucide-react'
import { Button } from '../ui/button'
import { ScrollArea } from '../ui/scroll-area'

// Tool icon mapping
const TOOL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  sandbox: Terminal,
  execute_python: Terminal,
  execute_node: FileCode,
  execute_bash: Terminal,
  web_search: Search,
  github_search: GitBranch,
  github_get_file: FileCode,
  ray_submit: Play,
  default: Wrench,
}

function getToolIcon(toolName: string) {
  // Check for partial matches
  const lowerName = toolName.toLowerCase()
  if (lowerName.includes('sandbox') || lowerName.includes('execute')) {
    return Terminal
  }
  if (lowerName.includes('github')) {
    return GitBranch
  }
  if (lowerName.includes('search')) {
    return Search
  }
  if (lowerName.includes('ray')) {
    return Play
  }
  return TOOL_ICONS[toolName] || TOOL_ICONS.default
}

interface ToolItemProps {
  tool: ToolExecution
  isExpanded: boolean
  onToggle: () => void
}

function ToolItem({ tool, isExpanded, onToggle }: ToolItemProps) {
  const [copied, setCopied] = useState(false)
  const Icon = getToolIcon(tool.name)

  const getStatusBadge = () => {
    switch (tool.status) {
      case 'completed':
      case 'approved':
        return (
          <span className="flex items-center gap-1 text-xs text-green-500 bg-green-500/10 px-2 py-0.5 rounded-full">
            <CheckCircle2 className="w-3 h-3" />
            {tool.status === 'approved' ? 'Approved' : 'Done'}
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
      case 'rejected':
        return (
          <span className="flex items-center gap-1 text-xs text-red-500 bg-red-500/10 px-2 py-0.5 rounded-full">
            <XCircle className="w-3 h-3" />
            {tool.status === 'rejected' ? 'Rejected' : 'Error'}
          </span>
        )
      case 'pending':
      default:
        return (
          <span className="flex items-center gap-1 text-xs text-gray-500 bg-gray-500/10 px-2 py-0.5 rounded-full">
            <Clock className="w-3 h-3" />
            Pending
          </span>
        )
    }
  }

  const formatDuration = () => {
    if (!tool.started_at || !tool.completed_at) return null
    const start = new Date(tool.started_at).getTime()
    const end = new Date(tool.completed_at).getTime()
    const ms = end - start
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const formatArguments = (args: Record<string, any>) => {
    try {
      return JSON.stringify(args, null, 2)
    } catch {
      return String(args)
    }
  }

  const formatResult = (result: any) => {
    if (!result) return null
    if (typeof result === 'string') return result
    try {
      return JSON.stringify(result, null, 2)
    } catch {
      return String(result)
    }
  }

  return (
    <div className="border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
      {/* Tool header */}
      <div
        className="flex items-center justify-between p-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-900"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-purple-500/10">
            <Icon className="w-4 h-4 text-purple-500" />
          </div>
          <div>
            <h4 className="font-medium text-sm">{tool.name}</h4>
            {formatDuration() && (
              <p className="text-xs text-muted-foreground">
                Duration: {formatDuration()}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {getStatusBadge()}
          <Button variant="ghost" size="sm" className="p-1 h-auto">
            {isExpanded ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>

      {/* Expanded content */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="p-3 border-t border-gray-200 dark:border-gray-800 space-y-3">
              {/* Arguments */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-muted-foreground">Arguments</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="p-1 h-auto"
                    onClick={() => handleCopy(formatArguments(tool.arguments))}
                  >
                    {copied ? (
                      <Check className="w-3 h-3 text-green-500" />
                    ) : (
                      <Copy className="w-3 h-3" />
                    )}
                  </Button>
                </div>
                <pre className="text-xs bg-gray-900 text-gray-100 p-2 rounded overflow-x-auto max-h-[100px]">
                  {formatArguments(tool.arguments)}
                </pre>
              </div>

              {/* Result */}
              {tool.result && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-muted-foreground">Result</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="p-1 h-auto"
                      onClick={() => handleCopy(formatResult(tool.result) || '')}
                    >
                      {copied ? (
                        <Check className="w-3 h-3 text-green-500" />
                      ) : (
                        <Copy className="w-3 h-3" />
                      )}
                    </Button>
                  </div>
                  <pre className="text-xs bg-gray-900 text-gray-100 p-2 rounded overflow-x-auto max-h-[150px]">
                    {formatResult(tool.result)}
                  </pre>
                </div>
              )}

              {/* Error */}
              {tool.error && (
                <div>
                  <span className="text-xs font-medium text-red-500">Error</span>
                  <div className="mt-1 p-2 rounded bg-red-500/10 border border-red-500/30">
                    <p className="text-xs text-red-500">{tool.error}</p>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

interface ToolExecutionDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ToolExecutionDrawer({ open, onOpenChange }: ToolExecutionDrawerProps) {
  const { tools, toolExecutionOrder } = useWorkflowStore()
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set())

  const toggleTool = (toolId: string) => {
    setExpandedTools((prev) => {
      const next = new Set(prev)
      if (next.has(toolId)) {
        next.delete(toolId)
      } else {
        next.add(toolId)
      }
      return next
    })
  }

  const toolList = toolExecutionOrder.map((id) => tools[id]).filter(Boolean)

  const completedCount = toolList.filter(
    (t) => t.status === 'completed' || t.status === 'approved'
  ).length
  const errorCount = toolList.filter(
    (t) => t.status === 'error' || t.status === 'rejected'
  ).length

  return (
    <Drawer.Root open={open} onOpenChange={onOpenChange}>
      <Drawer.Portal>
        <Drawer.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Drawer.Content className="bg-background flex flex-col rounded-t-[10px] h-[90vh] mt-24 fixed bottom-0 left-0 right-0 z-50">
          <div className="p-4 bg-background rounded-t-[10px] flex-1 overflow-hidden">
            {/* Handle */}
            <div className="mx-auto w-12 h-1.5 flex-shrink-0 rounded-full bg-gray-300 dark:bg-gray-700 mb-4" />

            {/* Header */}
            <div className="flex items-center justify-between mb-4">
              <div>
                <Drawer.Title className="font-semibold text-lg flex items-center gap-2">
                  <Wrench className="w-5 h-5 text-purple-500" />
                  Tool Executions
                </Drawer.Title>
                <Drawer.Description className="text-sm text-muted-foreground">
                  {toolList.length} tools • {completedCount} completed • {errorCount} errors
                </Drawer.Description>
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  if (expandedTools.size === toolList.length) {
                    setExpandedTools(new Set())
                  } else {
                    setExpandedTools(new Set(toolList.map((t) => t.id)))
                  }
                }}
              >
                {expandedTools.size === toolList.length ? 'Collapse All' : 'Expand All'}
              </Button>
            </div>

            {/* Tool list */}
            <ScrollArea className="h-[calc(90vh-140px)]">
              <div className="space-y-2 pr-4">
                {toolList.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <Wrench className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p>No tool executions yet</p>
                  </div>
                ) : (
                  toolList.map((tool) => (
                    <ToolItem
                      key={tool.id}
                      tool={tool}
                      isExpanded={expandedTools.has(tool.id)}
                      onToggle={() => toggleTool(tool.id)}
                    />
                  ))
                )}
              </div>
            </ScrollArea>
          </div>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  )
}

export default ToolExecutionDrawer
