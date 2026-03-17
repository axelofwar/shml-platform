import { useMutation, useQuery, UseQueryOptions, UseMutationOptions } from '@tanstack/react-query'
import type {
  AgentExecuteRequest,
  AgentExecuteResponse,
  PlaybookSummaryResponse,
  ReflectionAnalysisRequest,
  Reflection
} from '@/types'

const AGENT_API_BASE = import.meta.env.VITE_AGENT_API_URL || '/api/agent/v1'

// ============================================================================
// Agent Execution Hook
// ============================================================================

export interface UseAgentExecuteOptions extends Omit<UseMutationOptions<AgentExecuteResponse, Error, AgentExecuteRequest>, 'mutationFn'> {}

export const useAgentExecute = (options?: UseAgentExecuteOptions) => {
  return useMutation<AgentExecuteResponse, Error, AgentExecuteRequest>({
    mutationFn: async (request: AgentExecuteRequest) => {
      const res = await fetch(`${AGENT_API_BASE}/agent/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        credentials: 'include', // OAuth2 cookies
      })

      if (!res.ok) {
        const error = await res.json().catch(() => ({ error: res.statusText }))
        throw new Error(error.error || 'Agent execution failed')
      }

      return res.json()
    },
    ...options
  })
}

// ============================================================================
// Playbook Summary Hook
// ============================================================================

export interface UsePlaybookSummaryOptions extends Omit<UseQueryOptions<PlaybookSummaryResponse, Error>, 'queryKey' | 'queryFn'> {}

export const usePlaybookSummary = (userId: string, options?: UsePlaybookSummaryOptions) => {
  return useQuery<PlaybookSummaryResponse, Error>({
    queryKey: ['playbook', 'summary', userId],
    queryFn: async () => {
      const res = await fetch(`${AGENT_API_BASE}/playbook/${userId}/summary`, {
        credentials: 'include'
      })

      if (!res.ok) {
        const error = await res.json().catch(() => ({ error: res.statusText }))
        throw new Error(error.error || 'Failed to fetch playbook summary')
      }

      return res.json()
    },
    enabled: !!userId,
    staleTime: 5 * 60 * 1000, // 5 minutes
    ...options
  })
}

// ============================================================================
// Reflection Analysis Hook
// ============================================================================

export interface UseReflectionAnalyzeOptions extends Omit<UseMutationOptions<Reflection, Error, ReflectionAnalysisRequest>, 'mutationFn'> {}

export const useReflectionAnalyze = (options?: UseReflectionAnalyzeOptions) => {
  return useMutation<Reflection, Error, ReflectionAnalysisRequest>({
    mutationFn: async (request: ReflectionAnalysisRequest) => {
      const res = await fetch(`${AGENT_API_BASE}/reflection/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        credentials: 'include',
      })

      if (!res.ok) {
        const error = await res.json().catch(() => ({ error: res.statusText }))
        throw new Error(error.error || 'Reflection analysis failed')
      }

      return res.json()
    },
    ...options
  })
}

// ============================================================================
// Playbook CRUD Hooks
// ============================================================================

export interface UsePlaybookCreateOptions extends Omit<UseMutationOptions<any, Error, any>, 'mutationFn'> {}

export const usePlaybookCreate = (userId: string, options?: UsePlaybookCreateOptions) => {
  return useMutation({
    mutationFn: async (playbookData: any) => {
      const res = await fetch(`${AGENT_API_BASE}/playbook/${userId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(playbookData),
        credentials: 'include',
      })

      if (!res.ok) {
        const error = await res.json().catch(() => ({ error: res.statusText }))
        throw new Error(error.error || 'Failed to create playbook')
      }

      return res.json()
    },
    ...options
  })
}

export const usePlaybookUpdate = (userId: string, playbookId: string, options?: UsePlaybookCreateOptions) => {
  return useMutation({
    mutationFn: async (updates: any) => {
      const res = await fetch(`${AGENT_API_BASE}/playbook/${userId}/${playbookId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
        credentials: 'include',
      })

      if (!res.ok) {
        const error = await res.json().catch(() => ({ error: res.statusText }))
        throw new Error(error.error || 'Failed to update playbook')
      }

      return res.json()
    },
    ...options
  })
}

export const usePlaybookDelete = (userId: string, playbookId: string, options?: UsePlaybookCreateOptions) => {
  return useMutation({
    mutationFn: async () => {
      const res = await fetch(`${AGENT_API_BASE}/playbook/${userId}/${playbookId}`, {
        method: 'DELETE',
        credentials: 'include',
      })

      if (!res.ok) {
        const error = await res.json().catch(() => ({ error: res.statusText }))
        throw new Error(error.error || 'Failed to delete playbook')
      }

      return res.json()
    },
    ...options
  })
}

// ============================================================================
// Health Check Hook
// ============================================================================

export const useAgentHealth = () => {
  return useQuery({
    queryKey: ['agent', 'health'],
    queryFn: async () => {
      const res = await fetch(`${AGENT_API_BASE}/health`)

      if (!res.ok) {
        throw new Error('Agent service unhealthy')
      }

      return res.json()
    },
    refetchInterval: 30000, // Check every 30 seconds
    retry: 3
  })
}

// ============================================================================
// OpenAI-Compatible Chat Hook (for IDE integrations)
// ============================================================================

export interface OpenAIChatRequest {
  model: string
  messages: Array<{ role: string; content: string }>
  stream?: boolean
  temperature?: number
  max_tokens?: number
}

export interface OpenAIChatResponse {
  id: string
  object: string
  created: number
  model: string
  choices: Array<{
    index: number
    message: { role: string; content: string }
    finish_reason: string
  }>
  usage?: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  }
}

export const useOpenAIChat = (options?: UseMutationOptions<OpenAIChatResponse, Error, OpenAIChatRequest>) => {
  return useMutation<OpenAIChatResponse, Error, OpenAIChatRequest>({
    mutationFn: async (request: OpenAIChatRequest) => {
      const res = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...request, stream: false }),
        // No credentials - this endpoint is for IDE tools (no auth)
      })

      if (!res.ok) {
        const error = await res.json().catch(() => ({ error: res.statusText }))
        throw new Error(error.error || 'Chat completion failed')
      }

      return res.json()
    },
    ...options
  })
}
