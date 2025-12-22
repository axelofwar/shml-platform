import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import {
  Send,
  Loader2,
  Settings,
  History,
  Plus,
  Trash2,
  Copy,
  Check,
  Sparkles,
  Zap,
  ExternalLink,
  ChevronDown,
  X,
  MessageCircle,
  Info,
  StopCircle,
  Pencil,
} from 'lucide-react';
import type { ChatMessage, ConversationSummary, ModelInfo } from './types';
import * as api from './api';

// Model selection component
function ModelSelector({
  models,
  selected,
  onSelect,
}: {
  models: ModelInfo[];
  selected: string;
  onSelect: (model: string) => void;
}) {
  const [open, setOpen] = useState(false);

  const selectedModel = models.find((m) => m.id === selected) || models[0];

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-dark-800 border border-dark-600 hover:border-dark-500 transition-colors"
      >
        {selected === 'auto' ? (
          <Sparkles className="w-4 h-4 text-primary-400" />
        ) : selected.includes('30b') ? (
          <Sparkles className="w-4 h-4 text-purple-400" />
        ) : (
          <Zap className="w-4 h-4 text-yellow-400" />
        )}
        <span className="text-sm">{selectedModel?.name || 'Auto'}</span>
        <ChevronDown className="w-4 h-4" />
      </button>

      {open && (
        <div className="absolute top-full mt-1 left-0 w-72 bg-dark-800 border border-dark-600 rounded-lg shadow-xl z-50">
          {models.map((model) => (
            <button
              key={model.id}
              onClick={() => {
                onSelect(model.id);
                setOpen(false);
              }}
              className={`w-full px-4 py-3 text-left hover:bg-dark-700 transition-colors first:rounded-t-lg last:rounded-b-lg ${
                model.id === selected ? 'bg-dark-700' : ''
              }`}
            >
              <div className="flex items-center gap-2">
                {model.id === 'auto' ? (
                  <Sparkles className="w-4 h-4 text-primary-400" />
                ) : model.id.includes('30b') ? (
                  <Sparkles className="w-4 h-4 text-purple-400" />
                ) : (
                  <Zap className="w-4 h-4 text-yellow-400" />
                )}
                <span className="font-medium">{model.name}</span>
                {!model.is_available && model.id !== 'auto' && (
                  <span className="text-xs text-red-400 ml-auto">Offline</span>
                )}
              </div>
              <p className="text-xs text-dark-400 mt-1">{model.description}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Message component with markdown rendering
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function Message({
  message,
  isLast: _isLast,
  onEdit,
  isEditing,
}: {
  message: ChatMessage;
  isLast: boolean;
  onEdit?: () => void;
  isEditing?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const isEdited = message.edited === true;

  const copyToClipboard = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className={`py-6 ${isUser ? 'bg-dark-900' : 'bg-dark-800/50'} ${isEditing ? 'ring-2 ring-primary-500/50' : ''}`}
    >
      <div className="max-w-3xl mx-auto px-4">
        <div className="flex gap-4">
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
              isUser ? 'bg-primary-600' : 'bg-gradient-to-br from-purple-500 to-pink-500'
            }`}
          >
            {isUser ? (
              <span className="text-sm font-medium">U</span>
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <span className="font-medium text-sm">
                {isUser ? 'You' : 'SHML Assistant'}
              </span>
              {isEdited && (
                <span className="text-xs text-dark-500 italic">(edited)</span>
              )}
              {isUser && onEdit && (
                <button
                  onClick={onEdit}
                  className="p-1 rounded hover:bg-dark-700 transition-colors"
                  title="Edit message"
                >
                  <Pencil className="w-4 h-4 text-dark-400 hover:text-dark-200" />
                </button>
              )}
              {!isUser && (
                <button
                  onClick={copyToClipboard}
                  className="p-1 rounded hover:bg-dark-700 transition-colors"
                  title="Copy response"
                >
                  {copied ? (
                    <Check className="w-4 h-4 text-green-400" />
                  ) : (
                    <Copy className="w-4 h-4 text-dark-400" />
                  )}
                </button>
              )}
            </div>
            <div className="prose prose-invert max-w-none">
              <ReactMarkdown
                components={{
                  code({ node, inline, className, children, ...props }: any) {
                    const match = /language-(\w+)/.exec(className || '');
                    return !inline && match ? (
                      <SyntaxHighlighter
                        style={oneDark}
                        language={match[1]}
                        PreTag="div"
                        {...props}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                    ) : (
                      <code className={className} {...props}>
                        {children}
                      </code>
                    );
                  },
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Loading indicator with cancel button
function LoadingIndicator({ onCancel }: { onCancel?: () => void }) {
  return (
    <div className="py-6 bg-dark-800/50">
      <div className="max-w-3xl mx-auto px-4">
        <div className="flex gap-4">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
            <Sparkles className="w-4 h-4" />
          </div>
          <div className="flex items-center gap-3 pt-2">
            <div className="flex items-center gap-1">
              <div className="w-2 h-2 rounded-full bg-dark-400 loading-dot" />
              <div className="w-2 h-2 rounded-full bg-dark-400 loading-dot" />
              <div className="w-2 h-2 rounded-full bg-dark-400 loading-dot" />
            </div>
            {onCancel && (
              <button
                onClick={onCancel}
                className="flex items-center gap-1.5 px-2 py-1 text-xs text-red-400 hover:text-red-300 hover:bg-dark-700 rounded transition-colors"
                title="Cancel request"
              >
                <StopCircle className="w-3.5 h-3.5" />
                <span>Cancel</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// Sidebar with conversation history
function Sidebar({
  conversations,
  currentId,
  onSelect,
  onNew,
  onDelete,
  isOpen,
  onClose,
}: {
  conversations: ConversationSummary[];
  currentId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  isOpen: boolean;
  onClose: () => void;
}) {
  return (
    <>
      {/* Overlay for mobile */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed lg:static inset-y-0 left-0 w-72 bg-dark-900 border-r border-dark-700 flex flex-col z-50 transform transition-transform lg:transform-none ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-4 border-b border-dark-700">
          <button
            onClick={onNew}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-primary-600 hover:bg-primary-500 rounded-lg transition-colors"
          >
            <Plus className="w-5 h-5" />
            <span>New Chat</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {conversations.map((conv) => (
            <button
              key={conv.id}
              onClick={() => {
                onSelect(conv.id);
                onClose();
              }}
              className={`w-full group flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors mb-1 ${
                conv.id === currentId
                  ? 'bg-dark-700'
                  : 'hover:bg-dark-800'
              }`}
            >
              <History className="w-4 h-4 text-dark-400 shrink-0" />
              <span className="flex-1 truncate text-sm">
                {conv.title || conv.preview || 'New conversation'}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(conv.id);
                }}
                className="opacity-0 group-hover:opacity-100 p-1 hover:bg-dark-600 rounded transition-all"
              >
                <Trash2 className="w-4 h-4 text-dark-400" />
              </button>
            </button>
          ))}
        </div>

        {/* Close button for mobile */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-2 hover:bg-dark-800 rounded-lg lg:hidden"
        >
          <X className="w-5 h-5" />
        </button>
      </aside>
    </>
  );
}

// Main App component
export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState('auto');
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingMessageIndex, setEditingMessageIndex] = useState<number | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Load models and conversations on mount
  useEffect(() => {
    api.listModels().then((res) => setModels(res.data)).catch(console.error);
    api.listConversations().then((res) => setConversations(res.conversations)).catch(console.error);
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px';
  };

  // Create new conversation
  const handleNewChat = useCallback(async () => {
    setMessages([]);
    setCurrentConversationId(null);
    setError(null);
    setEditingMessageIndex(null);
    inputRef.current?.focus();
  }, []);

  // Load conversation
  const handleSelectConversation = useCallback(async (id: string) => {
    try {
      const conv = await api.getConversation(id);
      setMessages(conv.messages);
      setCurrentConversationId(id);
      setError(null);
      setEditingMessageIndex(null);
    } catch (e) {
      console.error('Failed to load conversation:', e);
    }
  }, []);

  // Delete conversation
  const handleDeleteConversation = useCallback(async (id: string) => {
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (currentConversationId === id) {
        handleNewChat();
      }
    } catch (e) {
      console.error('Failed to delete conversation:', e);
    }
  }, [currentConversationId, handleNewChat]);

  // Cancel ongoing request
  const handleCancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsLoading(false);
      setError('Request cancelled');
    }
  }, []);

  // Edit message - populate input and track which message is being edited
  const handleEditMessage = useCallback((index: number) => {
    const msg = messages[index];
    if (msg && msg.role === 'user') {
      setInput(msg.content);
      setEditingMessageIndex(index);
      inputRef.current?.focus();
    }
  }, [messages]);

  // Send message (handles both new messages and edits)
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    // Create abort controller for this request
    abortControllerRef.current = new AbortController();

    let updatedMessages: ChatMessage[];

    if (editingMessageIndex !== null) {
      // Editing an existing message - truncate history and replace
      const editedMessage: ChatMessage = {
        role: 'user',
        content: input.trim(),
        edited: true,
      };
      // Keep messages up to (but not including) the edited message, then add the edited one
      updatedMessages = [...messages.slice(0, editingMessageIndex), editedMessage];
      setMessages(updatedMessages);
      setEditingMessageIndex(null);
    } else {
      // New message
      const userMessage: ChatMessage = { role: 'user', content: input.trim() };
      updatedMessages = [...messages, userMessage];
      setMessages(updatedMessages);
    }

    setInput('');
    setIsLoading(true);
    setError(null);

    // Reset textarea height
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }

    try {
      // Create conversation if needed
      let convId = currentConversationId;
      if (!convId) {
        const { id } = await api.createConversation(selectedModel);
        convId = id;
        setCurrentConversationId(id);
      }

      // Send to API
      const response = await api.createChatCompletion({
        messages: updatedMessages,
        model: selectedModel,
        conversation_id: convId,
      });

      // Check if cancelled
      if (abortControllerRef.current?.signal.aborted) {
        return;
      }

      const assistantMessage = response.choices[0]?.message;
      if (assistantMessage) {
        setMessages((prev) => [...prev, assistantMessage]);
      }

      // Refresh conversation list
      const { conversations: updated } = await api.listConversations();
      setConversations(updated);
    } catch (e: any) {
      if (e.name === 'AbortError' || abortControllerRef.current?.signal.aborted) {
        // Request was cancelled, don't show error
        return;
      }
      console.error('Failed to send message:', e);
      setError(e.message || 'Failed to send message');
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  // Handle keyboard shortcuts
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  // Check if embedded (in iframe)
  const isEmbedded = window.self !== window.top;

  return (
    <div className="flex h-screen bg-dark-900 text-white">
      {/* Sidebar */}
      <Sidebar
        conversations={conversations}
        currentId={currentConversationId}
        onSelect={handleSelectConversation}
        onNew={handleNewChat}
        onDelete={handleDeleteConversation}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main content */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="flex items-center justify-between px-4 py-3 border-b border-dark-700">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(true)}
              className="p-2 hover:bg-dark-800 rounded-lg lg:hidden"
            >
              <History className="w-5 h-5" />
            </button>
            <h1 className="text-lg font-semibold hidden sm:block">SHML Chat</h1>
            {/* Ask Mode Badge */}
            <div className="flex items-center gap-1.5 px-2 py-1 bg-blue-900/40 border border-blue-700/50 rounded-full">
              <MessageCircle className="w-3.5 h-3.5 text-blue-400" />
              <span className="text-xs text-blue-300 font-medium">Ask Mode</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <ModelSelector
              models={models}
              selected={selectedModel}
              onSelect={setSelectedModel}
            />

            {isEmbedded && (
              <a
                href="/chat-ui"
                target="_blank"
                rel="noopener noreferrer"
                className="p-2 hover:bg-dark-800 rounded-lg"
                title="Open in new window"
              >
                <ExternalLink className="w-5 h-5" />
              </a>
            )}

            <button className="p-2 hover:bg-dark-800 rounded-lg">
              <Settings className="w-5 h-5" />
            </button>
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center max-w-lg px-4">
                <div className="w-16 h-16 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center mx-auto mb-4">
                  <MessageCircle className="w-8 h-8" />
                </div>
                <h2 className="text-xl font-semibold mb-2">SHML Assistant</h2>
                <p className="text-dark-400 mb-4">
                  Ask questions about the SHML Platform, architecture, code,
                  or get help with ML workflows and best practices.
                </p>

                {/* Ask-Only Mode Notice */}
                <div className="bg-blue-900/30 border border-blue-700/50 rounded-lg p-4 text-left">
                  <div className="flex items-start gap-3">
                    <Info className="w-5 h-5 text-blue-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-blue-200 font-medium text-sm mb-1">Ask Mode Only</p>
                      <p className="text-blue-300/80 text-xs">
                        This chat is for questions and learning. I can explain code and concepts,
                        but I cannot edit files or execute commands. For editing capabilities,
                        use <span className="font-medium">Cursor</span> with the SHML Chat API.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Example prompts */}
                <div className="mt-6 grid gap-2">
                  <button
                    onClick={() => setInput("What is the SHML Platform architecture?")}
                    className="text-left px-4 py-3 bg-dark-800/50 hover:bg-dark-800 rounded-lg border border-dark-600 transition-colors"
                  >
                    <span className="text-dark-300 text-sm">What is the SHML Platform architecture?</span>
                  </button>
                  <button
                    onClick={() => setInput("How do I submit a job to the Ray cluster?")}
                    className="text-left px-4 py-3 bg-dark-800/50 hover:bg-dark-800 rounded-lg border border-dark-600 transition-colors"
                  >
                    <span className="text-dark-300 text-sm">How do I submit a job to the Ray cluster?</span>
                  </button>
                  <button
                    onClick={() => setInput("Explain how MLflow experiment tracking works")}
                    className="text-left px-4 py-3 bg-dark-800/50 hover:bg-dark-800 rounded-lg border border-dark-600 transition-colors"
                  >
                    <span className="text-dark-300 text-sm">Explain how MLflow experiment tracking works</span>
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg, i) => (
                <Message
                  key={i}
                  message={msg}
                  isLast={i === messages.length - 1}
                  onEdit={msg.role === 'user' ? () => handleEditMessage(i) : undefined}
                  isEditing={editingMessageIndex === i}
                />
              ))}
              {isLoading && <LoadingIndicator onCancel={handleCancel} />}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="px-4 py-2 bg-red-900/50 border-t border-red-700 text-red-200 text-sm">
            {error}
          </div>
        )}

        {/* Input */}
        <div className="border-t border-dark-700 p-4">
          <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
            {/* Editing indicator */}
            {editingMessageIndex !== null && (
              <div className="flex items-center justify-between mb-2 px-2 py-1.5 bg-primary-900/30 border border-primary-700/50 rounded-lg">
                <div className="flex items-center gap-2 text-sm text-primary-300">
                  <Pencil className="w-4 h-4" />
                  <span>Editing message</span>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setEditingMessageIndex(null);
                    setInput('');
                  }}
                  className="text-xs text-primary-400 hover:text-primary-200 px-2 py-1 hover:bg-primary-900/50 rounded"
                >
                  Cancel edit
                </button>
              </div>
            )}
            <div className="relative flex items-end bg-dark-800 rounded-xl border border-dark-600 focus-within:border-primary-500 transition-colors">
              <textarea
                ref={inputRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                placeholder={editingMessageIndex !== null ? "Edit your message..." : "Ask a question about SHML Platform..."}
                rows={1}
                className="flex-1 bg-transparent px-4 py-3 resize-none focus:outline-none max-h-[200px]"
                disabled={isLoading}
              />
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="p-2 m-2 rounded-lg bg-primary-600 hover:bg-primary-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Send className="w-5 h-5" />
                )}
              </button>
            </div>
            <p className="text-xs text-dark-500 mt-2 text-center">
              Press Enter to send, Shift+Enter for new line
            </p>
          </form>
        </div>
      </main>
    </div>
  );
}
