/**
 * Type definitions for chat-ui-v2
 *
 * Shared types across stores, hooks, and components
 */

// ============================================================================
// API Types
// ============================================================================

export interface User {
  id: string
  email: string
  name: string
  roles: string[]
}

export interface Playbook {
  id: string
  user_id: string
  name: string
  patterns: PlaybookPattern[]
  created_at: string
  updated_at: string
}

export interface PlaybookPattern {
  context: string
  strategy: string
  confidence: number
  occurrences: number
}

export interface Reflection {
  id: string
  session_id: string
  type: 'success' | 'failure' | 'learning'
  content: string
  metadata: Record<string, any>
  created_at: string
}

// ============================================================================
// WebSocket Types (from agent-service)
// ============================================================================

export enum WSMessageType {
  STAGE_START = 'stage_start',
  STAGE_COMPLETE = 'stage_complete',
  STAGE_ERROR = 'stage_error',
  TOOL_CALL = 'tool_call',
  TOOL_RESULT = 'tool_result',
  TOOL_ERROR = 'tool_error',
  APPROVAL_REQUEST = 'approval_request',
  APPROVAL_RESPONSE = 'approval_response',
  THINKING = 'thinking',
  PROGRESS = 'progress',
  RESULT = 'result',
  ERROR = 'error',
  HEARTBEAT = 'heartbeat',
  ACK = 'ack',
}

export interface WSMessage {
  type: WSMessageType
  data: any
  timestamp: string
  session_id?: string
}

// Specific message data types
export interface StageStartData {
  stage: 'generator' | 'reflector' | 'curator'
  message: string
}

export interface StageCompleteData {
  stage: 'generator' | 'reflector' | 'curator'
  output: string
  duration_ms: number
}

export interface ToolCallData {
  tool_id: string
  tool_name: string
  arguments: Record<string, any>
  requires_approval: boolean
  risk_level?: 'low' | 'medium' | 'high'
}

export interface ToolResultData {
  tool_id: string
  result: any
  duration_ms: number
}

export interface ApprovalRequestData {
  approval_id: string
  tool_name: string
  arguments: Record<string, any>
  reasoning: string
  risk_level: 'low' | 'medium' | 'high'
}

export interface ThinkingData {
  stage: string
  thinking: string
}

export interface ProgressData {
  stage: string
  progress: number
  message: string
}

export interface ResultData {
  output: string
  metrics: {
    total_duration_ms: number
    generator_duration_ms?: number
    reflector_duration_ms?: number
    curator_duration_ms?: number
    tool_calls: number
    approvals: number
  }
}

// ============================================================================
// Chat Types
// ============================================================================

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  tool_calls?: ChatToolCall[]
  finish_reason?: string
  model?: string
}

export interface ChatToolCall {
  id: string
  type: string
  function: {
    name: string
    arguments: string
  }
  result?: any
  error?: string
  status: 'pending' | 'running' | 'completed' | 'error'
}

export interface ChatConversation {
  id: string
  title: string
  messages: ChatMessage[]
  created_at: string
  updated_at: string
  metadata?: {
    model?: string
    temperature?: number
    max_tokens?: number
  }
}

// ============================================================================
// Workflow Types
// ============================================================================

export enum ACEStage {
  IDLE = 'idle',
  VISION = 'vision',
  GENERATOR = 'generator',
  TOOLS = 'tools',
  REFLECTOR = 'reflector',
  CURATOR = 'curator',
  COMPLETE = 'complete',
  ERROR = 'error',
}

export interface WorkflowStageStatus {
  stage: ACEStage
  status: 'pending' | 'running' | 'completed' | 'error'
  started_at?: string
  completed_at?: string
  duration_ms?: number
  thinking?: string
  error?: string
}

export interface WorkflowToolExecution {
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

export interface WorkflowApprovalRequest {
  id: string
  tool_name: string
  arguments: Record<string, any>
  reasoning: string
  risk_level: 'low' | 'medium' | 'high'
  requested_at: string
  status: 'pending' | 'approved' | 'rejected'
}

export interface WorkflowMetrics {
  total_duration_ms: number
  generator_duration_ms?: number
  reflector_duration_ms?: number
  curator_duration_ms?: number
  tool_calls_count: number
  approvals_count: number
  tokens_used?: number
}

// ============================================================================
// UI Types
// ============================================================================

export type Theme = 'light' | 'dark' | 'system'

export interface ToastMessage {
  id: string
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  description?: string
  duration?: number
}

export interface CommandPaletteItem {
  id: string
  label: string
  description?: string
  icon?: string
  action: () => void
  shortcut?: string
  category?: string
}

// ============================================================================
// API Request/Response Types
// ============================================================================

export interface AgentExecuteRequest {
  prompt: string
  session_id?: string
  conversation_id?: string
  temperature?: number
  max_iterations?: number
}

export interface AgentExecuteResponse {
  session_id: string
  output: string
  stages: {
    generator: string
    reflector: string
    curator: string
  }
  tool_calls: number
  duration_ms: number
}

export interface PlaybookSummaryResponse {
  user_id: string
  total_sessions: number
  successful_patterns: number
  common_strategies: Array<{
    context: string
    strategy: string
    confidence: number
  }>
}

export interface ReflectionAnalysisRequest {
  session_id: string
  prompt: string
  outcome: string
  tool_calls: Array<{
    tool: string
    success: boolean
  }>
}

// ============================================================================
// Error Types
// ============================================================================

export interface AppError {
  code: string
  message: string
  details?: Record<string, any>
  timestamp: string
}

export class AgentError extends Error {
  code: string
  details?: Record<string, any>

  constructor(message: string, code: string = 'AGENT_ERROR', details?: Record<string, any>) {
    super(message)
    this.name = 'AgentError'
    this.code = code
    this.details = details
  }
}

export class WebSocketError extends Error {
  code: string

  constructor(message: string, code: string = 'WS_ERROR') {
    super(message)
    this.name = 'WebSocketError'
    this.code = code
  }
}
