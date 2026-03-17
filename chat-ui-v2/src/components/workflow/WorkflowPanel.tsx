/**
 * WorkflowPanel - Main container for ACE workflow visualization
 *
 * Features:
 * - Split-pane layout (resizable)
 * - Real-time workflow state updates
 * - Stage timeline visualization
 * - Tool execution tracking
 * - Collapsible on mobile
 */

import { useEffect, useState } from 'react'
import { useWorkflowStore } from '@/stores/workflowStore'
import { useUIStore } from '@/stores/uiStore'
import { ACEStage } from '@/types'
import { ChevronRight, ChevronLeft, Activity } from 'lucide-react'

interface WorkflowPanelProps {
  className?: string
}

export function WorkflowPanel({ className = '' }: WorkflowPanelProps) {
  const {
    isActive,
    currentStage,
    stages,
    tools,
    pendingApprovals,
    metrics
  } = useWorkflowStore()

  const {
    isWorkflowPanelOpen,
    workflowPanelHeight,
    toggleWorkflowPanel,
    setWorkflowPanelHeight
  } = useUIStore()

  const [isDragging, setIsDragging] = useState(false)
  const [startY, setStartY] = useState(0)
  const [startHeight, setStartHeight] = useState(workflowPanelHeight)

  // Handle resize drag
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true)
    setStartY(e.clientY)
    setStartHeight(workflowPanelHeight)
    e.preventDefault()
  }

  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e: MouseEvent) => {
      // When dragging up (lower clientY), panel should get taller
      // When dragging down (higher clientY), panel should get shorter
      const deltaY = startY - e.clientY
      const newHeight = Math.max(200, Math.min(600, startHeight + deltaY))
      setWorkflowPanelHeight(newHeight)
    }

    const handleMouseUp = () => {
      setIsDragging(false)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, startY, startHeight, setWorkflowPanelHeight])

  // Get stage color
  const getStageColor = (stage: ACEStage) => {
    switch (stage) {
      case ACEStage.GENERATOR:
        return 'text-blue-400'
      case ACEStage.TOOLS:
        return 'text-orange-400'
      case ACEStage.REFLECTOR:
        return 'text-purple-400'
      case ACEStage.CURATOR:
        return 'text-green-400'
      case ACEStage.COMPLETE:
        return 'text-emerald-400'
      case ACEStage.ERROR:
        return 'text-red-400'
      default:
        return 'text-gray-400'
    }
  }

  // Get stage icon
  const getStageIcon = (stage: ACEStage) => {
    const stageStatus = stages[stage]
    if (!stageStatus) return null

    const className = `w-4 h-4 ${stageStatus.status === 'completed' ? 'text-green-400' : stageStatus.status === 'running' ? 'text-blue-400 animate-pulse' : 'text-gray-600'}`

    return <Activity className={className} />
  }

  if (!isWorkflowPanelOpen) {
    return (
      <div className="fixed bottom-4 right-4 z-50">
        <button
          onClick={toggleWorkflowPanel}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg shadow-lg hover:bg-primary/90 transition-colors"
        >
          <Activity className="w-4 h-4" />
          <span className="font-medium">Show Workflow</span>
          <ChevronLeft className="w-4 h-4" />
        </button>
      </div>
    )
  }

  return (
    <div
      className={`fixed bottom-0 left-0 right-0 bg-background border-t border-border shadow-2xl z-30 ${className}`}
      style={{ height: `${workflowPanelHeight}px` }}
    >
      {/* Resize handle at top - drag to adjust chat/workflow split */}
      <div
        className={`absolute top-0 left-0 right-0 h-4 cursor-ns-resize hover:bg-primary/20 transition-colors ${isDragging ? 'bg-primary/30' : ''} flex items-center justify-center group`}
        onMouseDown={handleMouseDown}
        title="Drag to resize chat area"
      >
        <div className="w-16 h-1.5 bg-muted-foreground/40 group-hover:bg-primary/60 rounded-full transition-colors" />
      </div>

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border">
        <div className="flex items-center gap-3">
          <Activity className={`w-5 h-5 ${isActive ? 'text-blue-400 animate-pulse' : 'text-gray-400'}`} />
          <div>
            <h3 className="font-semibold text-sm">ACE Workflow</h3>
            <p className="text-xs text-muted-foreground">
              {isActive ? (
                <>
                  <span className={getStageColor(currentStage)}>
                    {currentStage.charAt(0).toUpperCase() + currentStage.slice(1)}
                  </span>
                  {' '}stage active
                </>
              ) : (
                'No active workflow'
              )}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Stats */}
          {isActive && metrics && (
            <div className="flex items-center gap-4 text-xs text-muted-foreground mr-4">
              <div>
                <span className="text-muted-foreground">Tools:</span>{' '}
                <span className="text-foreground font-medium">{metrics.tool_calls_count}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Approvals:</span>{' '}
                <span className="text-foreground font-medium">{metrics.approvals_count}</span>
              </div>
              {metrics.total_duration_ms > 0 && (
                <div>
                  <span className="text-muted-foreground">Duration:</span>{' '}
                  <span className="text-foreground font-medium">{(metrics.total_duration_ms / 1000).toFixed(1)}s</span>
                </div>
              )}
            </div>
          )}

          <button
            onClick={toggleWorkflowPanel}
            className="p-1 hover:bg-muted rounded transition-colors"
            title="Close workflow panel"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="overflow-auto h-[calc(100%-48px)] p-4">
        {!isActive ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Activity className="w-12 h-12 text-muted-foreground mb-4" />
            <p className="text-muted-foreground">No active workflow</p>
            <p className="text-sm text-muted-foreground/70 mt-1">
              Send a message to start the ACE agent workflow
            </p>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Stage Timeline - Vertical */}
            <div>
              <h4 className="text-sm font-semibold mb-3">Workflow Stages</h4>
              <div className="space-y-2">
                {[ACEStage.GENERATOR, ACEStage.TOOLS, ACEStage.REFLECTOR, ACEStage.CURATOR, ACEStage.COMPLETE].map((stage) => {
                  const stageStatus = stages[stage]
                  const isCompleted = stageStatus?.status === 'completed'
                  const isRunning = stageStatus?.status === 'running'
                  const isPending = !stageStatus || stageStatus.status === 'pending'

                  return (
                    <div
                      key={stage}
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg border transition-all ${
                        isRunning
                          ? 'bg-primary/10 border-primary'
                          : isCompleted
                          ? 'bg-green-500/10 border-green-500/50'
                          : 'bg-muted/50 border-border'
                      }`}
                    >
                      {getStageIcon(stage)}
                      <div className="flex-1">
                        <div className={`text-sm font-medium ${
                          isRunning
                            ? 'text-primary'
                            : isCompleted
                            ? 'text-green-400'
                            : 'text-muted-foreground'
                        }`}>
                          {stage.charAt(0).toUpperCase() + stage.slice(1)}
                        </div>
                        {stageStatus?.duration_ms && (
                          <div className="text-xs text-muted-foreground">
                            {(stageStatus.duration_ms / 1000).toFixed(1)}s
                          </div>
                        )}
                      </div>
                      {isCompleted && (
                        <div className="text-green-400">✓</div>
                      )}
                      {isRunning && (
                        <div className="w-2 h-2 bg-primary rounded-full animate-pulse" />
                      )}
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Tool Executions */}
            {Object.keys(tools).length > 0 && (
              <div>
                <h4 className="text-sm font-semibold mb-3">Tool Executions</h4>
                <div className="space-y-2">
                  {Object.values(tools).map((tool) => (
                    <div
                      key={tool.id}
                      className="flex items-center justify-between px-3 py-2 rounded-lg bg-muted/50 border border-border"
                    >
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${
                          tool.status === 'completed' ? 'bg-green-400' :
                          tool.status === 'error' ? 'bg-red-400' :
                          tool.status === 'pending' ? 'bg-yellow-400' :
                          'bg-blue-400 animate-pulse'
                        }`} />
                        <span className="text-sm font-medium">{tool.name}</span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {tool.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Pending Approvals */}
            {Object.keys(pendingApprovals).length > 0 && (
              <div>
                <h4 className="text-sm font-semibold mb-3 text-yellow-400">
                  Pending Approvals ({Object.keys(pendingApprovals).length})
                </h4>
                <div className="space-y-2">
                  {Object.values(pendingApprovals).map((approval) => (
                    <div
                      key={approval.id}
                      className="px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/50"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-medium">{approval.tool_name}</span>
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          approval.risk_level === 'high' ? 'bg-red-500/20 text-red-300' :
                          approval.risk_level === 'medium' ? 'bg-yellow-500/20 text-yellow-300' :
                          'bg-blue-500/20 text-blue-300'
                        }`}>
                          {approval.risk_level} risk
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground mb-2">{approval.reasoning}</p>
                      <div className="flex gap-2">
                        <button className="flex-1 px-3 py-1 text-xs bg-green-500/20 hover:bg-green-500/30 text-green-300 rounded transition-colors">
                          Approve
                        </button>
                        <button className="flex-1 px-3 py-1 text-xs bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded transition-colors">
                          Deny
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
