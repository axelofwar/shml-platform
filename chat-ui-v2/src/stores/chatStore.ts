/**
 * Chat Store - Manages conversations and messages
 *
 * Uses Zustand with immer middleware for immutable updates
 * Persists to localStorage for conversation history
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { immer } from 'zustand/middleware/immer'

// Attachment types for multimodal support
export interface MessageAttachment {
  id: string
  type: 'image' | 'pdf' | 'file' | 'link'
  url: string
  name: string
  size?: number
  mimeType?: string
  metadata?: {
    summary?: string      // AI-generated description
    extractedText?: string // OCR or PDF text extraction
    dimensions?: { width: number; height: number }
    pageCount?: number
  }
}

// Rubric scores from Reflector stage
export interface RubricScores {
  clarity: number
  completeness: number
  correctness: number
  actionability: number
}

// Decision context for transparency
export interface DecisionContext {
  generatorReasoning?: string
  rubricScores?: RubricScores
  toolExecutions?: Array<{
    tool: string
    status: 'pending' | 'running' | 'success' | 'error'
    duration?: number
    summary?: string
    output?: string
  }>
  lessonsLearned?: string[]
  usageInstructions?: string[]
}

// Message types
export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  // Multimodal attachments
  attachments?: MessageAttachment[]
  // Decision context (for agent responses)
  decisionContext?: DecisionContext
  // Optional metadata
  tool_calls?: ToolCall[]
  finish_reason?: string
  model?: string
}

export interface ToolCall {
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

// Conversation
export interface Conversation {
  id: string
  title: string
  messages: Message[]
  created_at: string
  updated_at: string
  metadata?: {
    model?: string
    temperature?: number
    max_tokens?: number
  }
  // Context summarization
  summary?: {
    content: string
    keyDecisions: string[]
    toolsUsed: string[]
    outcomes: string[]
    originalMessageCount: number
    tokensSaved: number
    timestamp: string
  }
}

// Store state
interface ChatState {
  // Current conversation
  currentConversationId: string | null
  conversations: Record<string, Conversation>

  // Input state
  inputText: string
  isStreaming: boolean

  // Actions
  createConversation: (title?: string) => string
  setCurrentConversation: (id: string) => void
  deleteConversation: (id: string) => void

  addMessage: (conversationId: string, message: Message) => void
  updateMessage: (conversationId: string, messageId: string, updates: Partial<Message>) => void
  deleteMessage: (conversationId: string, messageId: string) => void

  setInputText: (text: string) => void
  setIsStreaming: (isStreaming: boolean) => void

  clearCurrentConversation: () => void
  updateConversationTitle: (id: string, title: string) => void

  // Context summarization
  setConversationSummary: (id: string, summary: Conversation['summary']) => void
  clearConversationSummary: (id: string) => void
}

export const useChatStore = create<ChatState>()(
  persist(
    immer((set, get) => ({
      // Initial state
      currentConversationId: null,
      conversations: {},
      inputText: '',
      isStreaming: false,

      // Create new conversation
      createConversation: (title = 'New Conversation') => {
        const id = `conv-${Date.now()}`
        const conversation: Conversation = {
          id,
          title,
          messages: [],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }

        set((state) => {
          state.conversations[id] = conversation
          state.currentConversationId = id
        })

        return id
      },

      // Set active conversation
      setCurrentConversation: (id) => {
        set((state) => {
          if (state.conversations[id]) {
            state.currentConversationId = id
          }
        })
      },

      // Delete conversation
      deleteConversation: (id) => {
        set((state) => {
          delete state.conversations[id]
          if (state.currentConversationId === id) {
            state.currentConversationId = null
          }
        })
      },

      // Add message to conversation
      addMessage: (conversationId, message) => {
        set((state) => {
          const conversation = state.conversations[conversationId]
          if (conversation) {
            conversation.messages.push(message)
            conversation.updated_at = new Date().toISOString()
          }
        })
      },

      // Update existing message (for streaming)
      updateMessage: (conversationId, messageId, updates) => {
        set((state) => {
          const conversation = state.conversations[conversationId]
          if (conversation) {
            const message = conversation.messages.find((m) => m.id === messageId)
            if (message) {
              Object.assign(message, updates)
              conversation.updated_at = new Date().toISOString()
            }
          }
        })
      },

      // Delete message
      deleteMessage: (conversationId, messageId) => {
        set((state) => {
          const conversation = state.conversations[conversationId]
          if (conversation) {
            conversation.messages = conversation.messages.filter(
              (m) => m.id !== messageId
            )
            conversation.updated_at = new Date().toISOString()
          }
        })
      },

      // Update input text
      setInputText: (text) => {
        set((state) => {
          state.inputText = text
        })
      },

      // Set streaming state
      setIsStreaming: (isStreaming) => {
        set((state) => {
          state.isStreaming = isStreaming
        })
      },

      // Clear current conversation
      clearCurrentConversation: () => {
        set((state) => {
          const id = state.currentConversationId
          if (id && state.conversations[id]) {
            state.conversations[id].messages = []
            state.conversations[id].updated_at = new Date().toISOString()
          }
        })
      },

      // Update conversation title
      updateConversationTitle: (id, title) => {
        set((state) => {
          const conversation = state.conversations[id]
          if (conversation) {
            conversation.title = title
            conversation.updated_at = new Date().toISOString()
          }
        })
      },

      // Set conversation summary
      setConversationSummary: (id, summary) => {
        set((state) => {
          const conversation = state.conversations[id]
          if (conversation) {
            conversation.summary = summary
            conversation.updated_at = new Date().toISOString()
          }
        })
      },

      // Clear conversation summary
      clearConversationSummary: (id) => {
        set((state) => {
          const conversation = state.conversations[id]
          if (conversation) {
            conversation.summary = undefined
            conversation.updated_at = new Date().toISOString()
          }
        })
      },
    })),
    {
      name: 'shml-chat-storage',
      partialize: (state) => ({
        conversations: state.conversations,
        currentConversationId: state.currentConversationId,
      }),
    }
  )
)

// Selectors for derived state
export const useCurrentConversation = () => {
  return useChatStore((state) => {
    const id = state.currentConversationId
    return id ? state.conversations[id] : null
  })
}

export const useConversationList = () => {
  return useChatStore((state) =>
    Object.values(state.conversations).sort(
      (a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    )
  )
}

export const useCurrentMessages = () => {
  return useChatStore((state) => {
    const id = state.currentConversationId
    return id ? state.conversations[id]?.messages ?? [] : []
  })
}
