// API client for Chat API

import type {
  ChatCompletionRequest,
  ChatCompletionResponse,
  Conversation,
  ConversationSummary,
  ModelInfo,
  RateLimitStatus,
  APIKey,
  UserInstruction,
} from './types';

const API_BASE = '/chat';

class APIError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'APIError';
  }
}

async function fetchAPI<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    credentials: 'include', // Include cookies for OAuth
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new APIError(response.status, error.detail || response.statusText);
  }

  return response.json();
}

// Chat completions
export async function createChatCompletion(
  request: ChatCompletionRequest
): Promise<ChatCompletionResponse> {
  return fetchAPI('/v1/chat/completions', {
    method: 'POST',
    body: JSON.stringify({
      ...request,
      source: 'web',  // Always set source to 'web' for ask-only mode
    }),
  });
}

export async function* streamChatCompletion(
  request: ChatCompletionRequest
): AsyncGenerator<string, void, unknown> {
  const response = await fetch(`${API_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      ...request,
      stream: true,
      source: 'web',  // Always set source to 'web' for ask-only mode
    }),
  });

  if (!response.ok) {
    throw new APIError(response.status, 'Stream error');
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        if (data === '[DONE]') return;
        try {
          const parsed = JSON.parse(data);
          const content = parsed.choices?.[0]?.delta?.content;
          if (content) yield content;
        } catch {
          // Ignore parse errors
        }
      }
    }
  }
}

// Models
export async function listModels(): Promise<{ data: ModelInfo[] }> {
  return fetchAPI('/v1/models');
}

// Conversations
export async function createConversation(
  model: string = 'auto',
  title?: string
): Promise<{ id: string }> {
  const params = new URLSearchParams({ model });
  if (title) params.set('title', title);
  return fetchAPI(`/conversations?${params}`, { method: 'POST' });
}

export async function listConversations(
  limit: number = 50,
  offset: number = 0
): Promise<{ conversations: ConversationSummary[]; total: number; has_more: boolean }> {
  return fetchAPI(`/conversations?limit=${limit}&offset=${offset}`);
}

export async function getConversation(id: string): Promise<Conversation> {
  return fetchAPI(`/conversations/${id}`);
}

export async function deleteConversation(id: string): Promise<void> {
  await fetchAPI(`/conversations/${id}`, { method: 'DELETE' });
}

// Rate limits
export async function getRateLimit(): Promise<RateLimitStatus> {
  return fetchAPI('/rate-limit');
}

// API Keys
export async function createAPIKey(
  name: string,
  description?: string
): Promise<APIKey> {
  return fetchAPI('/api-keys', {
    method: 'POST',
    body: JSON.stringify({ name, description }),
  });
}

export async function listAPIKeys(): Promise<{ keys: APIKey[]; total: number }> {
  return fetchAPI('/api-keys');
}

export async function revokeAPIKey(id: string): Promise<void> {
  await fetchAPI(`/api-keys/${id}`, { method: 'DELETE' });
}

// Instructions
export async function createInstruction(
  name: string,
  content: string,
  scope: 'user' | 'platform' = 'user'
): Promise<UserInstruction> {
  return fetchAPI('/instructions', {
    method: 'POST',
    body: JSON.stringify({ name, content, scope }),
  });
}

export async function listInstructions(): Promise<{ instructions: UserInstruction[]; total: number }> {
  return fetchAPI('/instructions');
}

export async function updateInstruction(
  id: string,
  data: { name: string; content: string; is_active?: boolean }
): Promise<UserInstruction> {
  return fetchAPI(`/instructions/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteInstruction(id: string): Promise<void> {
  await fetchAPI(`/instructions/${id}`, { method: 'DELETE' });
}

// Health
export async function checkHealth(): Promise<{
  status: string;
  version: string;
  services: { name: string; status: string }[];
}> {
  return fetchAPI('/health');
}
