/**
 * ChatLayout - Main layout with sidebar, chat area, and header controls
 *
 * Features:
 * - Collapsible conversation sidebar
 * - Header with new chat, clear history, context info
 * - Responsive design
 * - Keyboard shortcuts
 */

import { useState, useCallback, useEffect } from 'react'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { useAuthStore } from '@/stores/authStore'
import { ConversationSidebar } from '@/components/sidebar/ConversationSidebar'
import { ChatInterface } from './ChatInterface'
import { WorkflowPanel } from '@/components/workflow/WorkflowPanel'
import { TokenBudgetIndicator } from './TokenBudgetIndicator'
import { toast } from 'sonner'
import type { UserRole } from '@/lib/tokenBudget'
import {
  PanelLeftClose,
  PanelLeft,
  MessageSquarePlus,
  Trash2,
  Sparkles,
  User,
  Command
} from 'lucide-react'

export function ChatLayout() {
  const [showClearConfirm, setShowClearConfirm] = useState(false)

  // Auth store - fetch user on mount
  const { user, isLoading, error, fetchUser } = useAuthStore()

  useEffect(() => {
    fetchUser()
  }, [fetchUser])

  // Use authenticated user's role, fallback to developer for loading state
  const userRole: UserRole = user?.primary_role || 'developer'

  const {
    isSidebarOpen,
    toggleSidebar,
    sidebarWidth
  } = useUIStore()

  const {
    currentConversationId,
    conversations,
    createConversation,
    clearCurrentConversation,
    setCurrentConversation
  } = useChatStore()

  // Get current conversation
  const currentConversation = currentConversationId
    ? conversations[currentConversationId]
    : null

  // Handle new chat
  const handleNewChat = useCallback(() => {
    const id = createConversation('New Chat')
    setCurrentConversation(id)
    toast.success('New conversation created')
  }, [createConversation, setCurrentConversation])

  // Handle clear history
  const handleClearHistory = useCallback(() => {
    if (showClearConfirm) {
      clearCurrentConversation()
      setShowClearConfirm(false)
      toast.success('Conversation cleared')
    } else {
      setShowClearConfirm(true)
      toast.info('Click again to confirm clearing conversation', {
        duration: 3000,
      })
      // Auto-dismiss after 3 seconds
      setTimeout(() => setShowClearConfirm(false), 3000)
    }
  }, [showClearConfirm, clearCurrentConversation])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd/Ctrl + N: New chat
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        e.preventDefault()
        handleNewChat()
      }
      // Cmd/Ctrl + B: Toggle sidebar
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault()
        toggleSidebar()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleNewChat, toggleSidebar])

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      {/* Sidebar */}
      {isSidebarOpen && (
        <div
          className="flex-shrink-0 border-r border-border"
          style={{ width: `${sidebarWidth}px` }}
        >
          <ConversationSidebar />
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="flex items-center justify-between px-4 py-2 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          {/* Left side: Toggle + Title */}
          <div className="flex items-center gap-3">
            <button
              onClick={toggleSidebar}
              className="p-2 hover:bg-muted rounded-lg transition-colors"
              title={isSidebarOpen ? 'Hide sidebar (⌘B)' : 'Show sidebar (⌘B)'}
            >
              {isSidebarOpen ? (
                <PanelLeftClose className="w-5 h-5" />
              ) : (
                <PanelLeft className="w-5 h-5" />
              )}
            </button>

            <div className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-primary" />
              <span className="font-semibold">
                {currentConversation?.title || 'SHML Agent'}
              </span>
            </div>
          </div>

          {/* Center: Context usage - TokenBudgetIndicator (compact) with role */}
          <TokenBudgetIndicator compact userRole={userRole} />

          {/* Right side: Actions */}
          <div className="flex items-center gap-2">
            {/* Authenticated user info */}
            {isLoading ? (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-800/50 rounded-lg border border-zinc-700/50">
                <div className="w-4 h-4 border-2 border-zinc-600 border-t-zinc-400 rounded-full animate-spin" />
                <span className="text-xs text-zinc-400">Loading...</span>
              </div>
            ) : error ? (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-red-500/10 rounded-lg border border-red-500/30">
                <span className="text-xs text-red-400">{error}</span>
              </div>
            ) : user ? (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-800/50 rounded-lg border border-zinc-700/50">
                <User className="w-4 h-4 text-zinc-400" />
                <div className="flex flex-col">
                  <span className="text-xs font-medium text-zinc-300">
                    {user.preferred_username}
                  </span>
                  <span className="text-[10px] text-zinc-500 uppercase">
                    {user.primary_role}
                  </span>
                </div>
              </div>
            ) : null}

            {/* Command Palette Hint */}
            <button
              onClick={() => {
                // Trigger Cmd+K event
                const event = new KeyboardEvent('keydown', {
                  key: 'k',
                  metaKey: true,
                  bubbles: true
                })
                document.dispatchEvent(event)
              }}
              className="hidden sm:flex items-center gap-1.5 px-2.5 py-1.5 bg-muted/50 rounded-lg text-xs text-muted-foreground hover:bg-muted transition-colors border border-border"
              title="Open command palette (⌘K)"
            >
              <Command className="w-3 h-3" />
              <span>K</span>
            </button>

            <button
              onClick={handleNewChat}
              className="flex items-center gap-2 px-3 py-1.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-sm"
              title="New chat (⌘N)"
            >
              <MessageSquarePlus className="w-4 h-4" />
              <span className="hidden sm:inline">New Chat</span>
            </button>

            <button
              onClick={handleClearHistory}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-colors text-sm ${
                showClearConfirm
                  ? 'bg-red-500 text-white hover:bg-red-600'
                  : 'bg-muted hover:bg-muted/80'
              }`}
              title="Clear conversation"
            >
              <Trash2 className="w-4 h-4" />
              <span className="hidden sm:inline">
                {showClearConfirm ? 'Click to confirm' : 'Clear'}
              </span>
            </button>
          </div>
        </header>

        {/* Chat area */}
        <div className="flex-1 relative overflow-hidden">
          <ChatInterface />
        </div>
      </div>

      {/* Workflow Panel (fixed at bottom) */}
      <WorkflowPanel />
    </div>
  )
}
