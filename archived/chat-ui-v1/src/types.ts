// API types matching the backend schemas

export type UserRole = 'admin' | 'developer' | 'viewer';

export interface User {
  id: string;
  email?: string;
  name?: string;
  role: UserRole;
  groups: string[];
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  name?: string;
  edited?: boolean;  // Flag to show if message was edited
}

export type RequestSource = 'web' | 'api';

export interface ChatCompletionRequest {
  messages: ChatMessage[];
  model?: string;
  temperature?: number;
  max_tokens?: number;
  stream?: boolean;
  conversation_id?: string;
  include_instructions?: boolean;
  source?: RequestSource;  // 'web' for ask-only mode, 'api' for full capabilities
}

export interface ChatCompletionResponse {
  id: string;
  created: number;
  model: string;
  choices: {
    index: number;
    message: ChatMessage;
    finish_reason?: string;
  }[];
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  conversation_id?: string;
  model_selection?: string;
}

export interface Conversation {
  id: string;
  title?: string;
  model: string;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
}

export interface ConversationSummary {
  id: string;
  title?: string;
  model: string;
  message_count: number;
  created_at: string;
  updated_at: string;
  preview?: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  description: string;
  context_length: number;
  is_available: boolean;
  gpu: string;
  vram_gb: number;
  recommended_for: string[];
}

export interface RateLimitStatus {
  requests_remaining: number;
  requests_limit: number;
  reset_at: string;
  is_limited: boolean;
  role: UserRole;
}

export interface APIKey {
  id: string;
  name: string;
  description?: string;
  user_id: string;
  role: UserRole;
  created_at: string;
  expires_at?: string;
  last_used_at?: string;
  is_active: boolean;
  key?: string; // Only on creation
}

export interface UserInstruction {
  id: string;
  user_id: string;
  scope: 'user' | 'platform';
  name: string;
  content: string;
  is_active: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
}
