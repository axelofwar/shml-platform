/**
 * Workflow Store - Manages ACE (Generator-Reflector-Curator) workflow state
 *
 * Tracks the progression through ACE stages, tool execution, and approval workflows
 */

import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

// ACE Stages
export enum ACEStage {
  IDLE = 'idle',
  VISION = 'vision',  // Multi-modal vision analysis (Qwen3-VL)
  GENERATOR = 'generator',
  TOOLS = 'tools',
  REFLECTOR = 'reflector',
  CURATOR = 'curator',
  COMPLETE = 'complete',
  ERROR = 'error',
}

// Stage status
export interface StageStatus {
  stage: ACEStage
  status: 'pending' | 'running' | 'completed' | 'error'
  started_at?: string
  completed_at?: string
  duration_ms?: number
  thinking?: string // Current thinking text
  error?: string
}

// Tool execution status
export interface ToolExecution {
  id: string
  name: string
  arguments: Record<string, any>
  status: 'pending' | 'running' | 'completed' | 'error' | 'approved' | 'rejected'
  result?: any
  error?: string
  started_at: string
  completed_at?: string
  requires_approval?: boolean
  approval_requested_at?: string
}

// Approval request
export interface ApprovalRequest {
  id: string
  tool_name: string
  arguments: Record<string, any>
  reasoning: string
  risk_level: 'low' | 'medium' | 'high'
  requested_at: string
  status: 'pending' | 'approved' | 'rejected'
}

// Workflow metrics
export interface WorkflowMetrics {
  total_duration_ms: number
  generator_duration_ms?: number
  reflector_duration_ms?: number
  curator_duration_ms?: number
  tool_calls_count: number
  approvals_count: number
  tokens_used?: number
}

// Store state
interface WorkflowState {
  // Current workflow session
  sessionId: string | null
  isActive: boolean

  // ACE stage tracking
  currentStage: ACEStage
  stages: Record<ACEStage, StageStatus>

  // Tool execution
  tools: Record<string, ToolExecution>
  toolExecutionOrder: string[] // Maintains order

  // Approval workflow
  pendingApprovals: Record<string, ApprovalRequest>
  approvalHistory: ApprovalRequest[]

  // Metrics
  metrics: WorkflowMetrics

  // Actions
  startWorkflow: (sessionId: string) => void
  endWorkflow: () => void
  resetWorkflow: () => void

  setStage: (stage: ACEStage) => void
  updateStageStatus: (stage: ACEStage, updates: Partial<StageStatus>) => void

  addTool: (tool: ToolExecution) => void
  updateTool: (toolId: string, updates: Partial<ToolExecution>) => void

  addApprovalRequest: (request: ApprovalRequest) => void
  approveRequest: (requestId: string) => void
  rejectRequest: (requestId: string) => void

  updateMetrics: (updates: Partial<WorkflowMetrics>) => void
}

const initialStageStatus: StageStatus = {
  stage: ACEStage.IDLE,
  status: 'pending',
}

const initialMetrics: WorkflowMetrics = {
  total_duration_ms: 0,
  tool_calls_count: 0,
  approvals_count: 0,
}

export const useWorkflowStore = create<WorkflowState>()(
  immer((set, get) => ({
    // Initial state
    sessionId: null,
    isActive: false,
    currentStage: ACEStage.IDLE,
    stages: {
      [ACEStage.IDLE]: initialStageStatus,
      [ACEStage.VISION]: { ...initialStageStatus, stage: ACEStage.VISION },
      [ACEStage.GENERATOR]: { ...initialStageStatus, stage: ACEStage.GENERATOR },
      [ACEStage.TOOLS]: { ...initialStageStatus, stage: ACEStage.TOOLS },
      [ACEStage.REFLECTOR]: { ...initialStageStatus, stage: ACEStage.REFLECTOR },
      [ACEStage.CURATOR]: { ...initialStageStatus, stage: ACEStage.CURATOR },
      [ACEStage.COMPLETE]: { ...initialStageStatus, stage: ACEStage.COMPLETE },
      [ACEStage.ERROR]: { ...initialStageStatus, stage: ACEStage.ERROR },
    },
    tools: {},
    toolExecutionOrder: [],
    pendingApprovals: {},
    approvalHistory: [],
    metrics: initialMetrics,

    // Start new workflow session
    startWorkflow: (sessionId) => {
      set((state) => {
        state.sessionId = sessionId
        state.isActive = true
        state.currentStage = ACEStage.GENERATOR
        state.stages[ACEStage.GENERATOR].status = 'running'
        state.stages[ACEStage.GENERATOR].started_at = new Date().toISOString()
      })
    },

    // End workflow
    endWorkflow: () => {
      set((state) => {
        state.isActive = false
        state.currentStage = ACEStage.COMPLETE
        state.stages[ACEStage.COMPLETE].status = 'completed'
        state.stages[ACEStage.COMPLETE].completed_at = new Date().toISOString()
      })
    },

    // Reset workflow state
    resetWorkflow: () => {
      set((state) => {
        state.sessionId = null
        state.isActive = false
        state.currentStage = ACEStage.IDLE
        state.stages = {
          [ACEStage.IDLE]: initialStageStatus,
          [ACEStage.VISION]: { ...initialStageStatus, stage: ACEStage.VISION },
          [ACEStage.GENERATOR]: { ...initialStageStatus, stage: ACEStage.GENERATOR },
          [ACEStage.TOOLS]: { ...initialStageStatus, stage: ACEStage.TOOLS },
          [ACEStage.REFLECTOR]: { ...initialStageStatus, stage: ACEStage.REFLECTOR },
          [ACEStage.CURATOR]: { ...initialStageStatus, stage: ACEStage.CURATOR },
          [ACEStage.COMPLETE]: { ...initialStageStatus, stage: ACEStage.COMPLETE },
          [ACEStage.ERROR]: { ...initialStageStatus, stage: ACEStage.ERROR },
        }
        state.tools = {}
        state.toolExecutionOrder = []
        state.pendingApprovals = {}
        state.approvalHistory = []
        state.metrics = initialMetrics
      })
    },

    // Set current stage
    setStage: (stage) => {
      set((state) => {
        // Complete previous stage
        if (state.currentStage !== ACEStage.IDLE) {
          const prevStage = state.stages[state.currentStage]
          if (prevStage.status === 'running') {
            prevStage.status = 'completed'
            prevStage.completed_at = new Date().toISOString()
            if (prevStage.started_at) {
              prevStage.duration_ms =
                new Date().getTime() - new Date(prevStage.started_at).getTime()
            }
          }
        }

        // Start new stage
        state.currentStage = stage
        const newStage = state.stages[stage]
        newStage.status = 'running'
        newStage.started_at = new Date().toISOString()
      })
    },

    // Update stage status
    updateStageStatus: (stage, updates) => {
      set((state) => {
        const stageStatus = state.stages[stage]
        Object.assign(stageStatus, updates)
      })
    },

    // Add tool execution
    addTool: (tool) => {
      set((state) => {
        state.tools[tool.id] = tool
        state.toolExecutionOrder.push(tool.id)
        state.metrics.tool_calls_count += 1
      })
    },

    // Update tool execution
    updateTool: (toolId, updates) => {
      set((state) => {
        const tool = state.tools[toolId]
        if (tool) {
          Object.assign(tool, updates)

          // Calculate duration if completed
          if (updates.status === 'completed' || updates.status === 'error') {
            tool.completed_at = new Date().toISOString()
          }
        }
      })
    },

    // Add approval request
    addApprovalRequest: (request) => {
      set((state) => {
        state.pendingApprovals[request.id] = request
        state.metrics.approvals_count += 1
      })
    },

    // Approve request
    approveRequest: (requestId) => {
      set((state) => {
        const request = state.pendingApprovals[requestId]
        if (request) {
          request.status = 'approved'
          state.approvalHistory.push({ ...request })
          delete state.pendingApprovals[requestId]
        }
      })
    },

    // Reject request
    rejectRequest: (requestId) => {
      set((state) => {
        const request = state.pendingApprovals[requestId]
        if (request) {
          request.status = 'rejected'
          state.approvalHistory.push({ ...request })
          delete state.pendingApprovals[requestId]
        }
      })
    },

    // Update metrics
    updateMetrics: (updates) => {
      set((state) => {
        Object.assign(state.metrics, updates)
      })
    },
  }))
)

// Selectors
export const useCurrentStageStatus = () => {
  return useWorkflowStore((state) => state.stages[state.currentStage])
}

export const usePendingApprovalsList = () => {
  return useWorkflowStore((state) => Object.values(state.pendingApprovals))
}

export const useToolExecutionList = () => {
  return useWorkflowStore((state) =>
    state.toolExecutionOrder.map((id) => state.tools[id]).filter(Boolean)
  )
}
