/**
 * CommandPalette - Keyboard-driven command interface
 *
 * Features:
 * - Cmd+K / Ctrl+K to open
 * - Search conversations
 * - Quick actions (new chat, clear, toggle sidebar)
 * - Keyboard navigation
 */

import { useState, useEffect, useCallback } from 'react'
import { Command } from 'cmdk'
import { useChatStore } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { toast } from 'sonner'
import {
  MessageSquarePlus,
  Trash2,
  PanelLeft,
  Search,
  MessageSquare,
  Settings,
  Moon,
  Sun,
  Download,
  Upload,
  Sparkles,
  History,
  X
} from 'lucide-react'

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  const {
    conversations,
    createConversation,
    setCurrentConversation,
    clearCurrentConversation,
    currentConversationId
  } = useChatStore()

  const {
    toggleSidebar,
    isSidebarOpen,
    theme,
    setTheme
  } = useUIStore()

  // Toggle with Cmd+K / Ctrl+K
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((open) => !open)
      }
      // Escape to close
      if (e.key === 'Escape' && open) {
        setOpen(false)
      }
    }

    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [open])

  // Reset search when closing
  useEffect(() => {
    if (!open) {
      setSearch('')
    }
  }, [open])

  // Actions
  const handleNewChat = useCallback(() => {
    const id = createConversation('New Chat')
    setCurrentConversation(id)
    setOpen(false)
    toast.success('Created new conversation')
  }, [createConversation, setCurrentConversation])

  const handleClearChat = useCallback(() => {
    clearCurrentConversation()
    setOpen(false)
    toast.success('Conversation cleared')
  }, [clearCurrentConversation])

  const handleToggleSidebar = useCallback(() => {
    toggleSidebar()
    setOpen(false)
    toast.info(isSidebarOpen ? 'Sidebar hidden' : 'Sidebar shown')
  }, [toggleSidebar, isSidebarOpen])

  const handleToggleTheme = useCallback(() => {
    const newTheme = theme === 'dark' ? 'light' : 'dark'
    setTheme(newTheme)
    setOpen(false)
    toast.info(`Switched to ${newTheme} mode`)
  }, [theme, setTheme])

  const handleSelectConversation = useCallback((id: string) => {
    setCurrentConversation(id)
    setOpen(false)
    const conv = conversations[id]
    toast.success(`Switched to "${conv?.title || 'conversation'}"`)
  }, [setCurrentConversation, conversations])

  const handleExportConversations = useCallback(() => {
    const data = JSON.stringify(conversations, null, 2)
    const blob = new Blob([data], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `shml-conversations-${new Date().toISOString().split('T')[0]}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    setOpen(false)
    toast.success('Conversations exported')
  }, [conversations])

  // Get sorted conversations
  const sortedConversations = Object.values(conversations)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())

  // Filter conversations by search
  const filteredConversations = sortedConversations.filter(conv =>
    conv.title.toLowerCase().includes(search.toLowerCase()) ||
    conv.messages.some(m => m.content.toLowerCase().includes(search.toLowerCase()))
  )

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={() => setOpen(false)}
      />

      {/* Command Dialog */}
      <div className="absolute left-1/2 top-1/4 -translate-x-1/2 w-full max-w-lg">
        <Command
          className="rounded-xl border border-border bg-background shadow-2xl overflow-hidden"
          shouldFilter={false}
        >
          {/* Search Input */}
          <div className="flex items-center border-b border-border px-3">
            <Search className="w-4 h-4 text-muted-foreground mr-2" />
            <Command.Input
              value={search}
              onValueChange={setSearch}
              placeholder="Search conversations or type a command..."
              className="flex-1 h-12 bg-transparent outline-none placeholder:text-muted-foreground text-foreground"
            />
            <button
              onClick={() => setOpen(false)}
              className="p-1 hover:bg-muted rounded"
            >
              <X className="w-4 h-4 text-muted-foreground" />
            </button>
          </div>

          <Command.List className="max-h-[400px] overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results found.
            </Command.Empty>

            {/* Quick Actions */}
            <Command.Group heading="Actions" className="pb-2">
              <Command.Item
                onSelect={handleNewChat}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer hover:bg-muted aria-selected:bg-muted"
              >
                <MessageSquarePlus className="w-4 h-4 text-primary" />
                <span>New Chat</span>
                <kbd className="ml-auto text-xs bg-muted px-2 py-0.5 rounded">⌘N</kbd>
              </Command.Item>

              <Command.Item
                onSelect={handleClearChat}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer hover:bg-muted aria-selected:bg-muted"
              >
                <Trash2 className="w-4 h-4 text-destructive" />
                <span>Clear Current Chat</span>
              </Command.Item>

              <Command.Item
                onSelect={handleToggleSidebar}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer hover:bg-muted aria-selected:bg-muted"
              >
                <PanelLeft className="w-4 h-4" />
                <span>{isSidebarOpen ? 'Hide Sidebar' : 'Show Sidebar'}</span>
                <kbd className="ml-auto text-xs bg-muted px-2 py-0.5 rounded">⌘B</kbd>
              </Command.Item>

              <Command.Item
                onSelect={handleToggleTheme}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer hover:bg-muted aria-selected:bg-muted"
              >
                {theme === 'dark' ? (
                  <Sun className="w-4 h-4 text-yellow-500" />
                ) : (
                  <Moon className="w-4 h-4 text-blue-500" />
                )}
                <span>Toggle {theme === 'dark' ? 'Light' : 'Dark'} Mode</span>
              </Command.Item>

              <Command.Item
                onSelect={handleExportConversations}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer hover:bg-muted aria-selected:bg-muted"
              >
                <Download className="w-4 h-4 text-green-500" />
                <span>Export Conversations</span>
              </Command.Item>
            </Command.Group>

            {/* Recent Conversations */}
            {filteredConversations.length > 0 && (
              <Command.Group heading="Recent Conversations" className="pt-2 border-t border-border">
                {filteredConversations.slice(0, 8).map((conv) => (
                  <Command.Item
                    key={conv.id}
                    value={conv.id}
                    onSelect={() => handleSelectConversation(conv.id)}
                    className={`flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer hover:bg-muted aria-selected:bg-muted ${
                      conv.id === currentConversationId ? 'bg-primary/10 border border-primary/30' : ''
                    }`}
                  >
                    <MessageSquare className="w-4 h-4 text-muted-foreground" />
                    <div className="flex-1 min-w-0">
                      <div className="truncate text-sm">{conv.title}</div>
                      <div className="text-xs text-muted-foreground">
                        {conv.messages.length} messages • {new Date(conv.updated_at).toLocaleDateString()}
                      </div>
                    </div>
                    {conv.id === currentConversationId && (
                      <Sparkles className="w-4 h-4 text-primary" />
                    )}
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>

          {/* Footer */}
          <div className="border-t border-border px-3 py-2 text-xs text-muted-foreground flex items-center justify-between">
            <div className="flex items-center gap-4">
              <span>↑↓ Navigate</span>
              <span>↵ Select</span>
              <span>Esc Close</span>
            </div>
            <span>⌘K to toggle</span>
          </div>
        </Command>
      </div>
    </div>
  )
}
