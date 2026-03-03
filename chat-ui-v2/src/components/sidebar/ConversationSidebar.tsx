/**
 * ConversationSidebar - Conversation list and management
 *
 * Features:
 * - List all conversations
 * - Create new conversation
 * - Switch between conversations
 * - Delete conversations
 * - Search conversations
 */

import { useState } from 'react'
import { useChatStore, useConversationList } from '@/stores/chatStore'
import { MessageSquarePlus, Trash2, Search, Calendar } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export function ConversationSidebar() {
  const [searchQuery, setSearchQuery] = useState('')
  const conversations = useConversationList()
  const {
    currentConversationId,
    createConversation,
    setCurrentConversation,
    deleteConversation
  } = useChatStore()

  const handleNewChat = () => {
    const id = createConversation('New Chat')
    setCurrentConversation(id)
  }

  const handleDelete = (id: string, event: React.MouseEvent) => {
    event.stopPropagation()
    if (confirm('Delete this conversation? This cannot be undone.')) {
      deleteConversation(id)
    }
  }

  const filteredConversations = conversations.filter((conv) =>
    conv.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    conv.messages.some((msg) =>
      msg.content.toLowerCase().includes(searchQuery.toLowerCase())
    )
  )

  return (
    <div className="flex flex-col h-full bg-background border-r border-border">
      {/* Header */}
      <div className="p-4 border-b border-border space-y-3">
        <button
          onClick={handleNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
        >
          <MessageSquarePlus className="w-4 h-4" />
          <span className="font-medium">New Chat</span>
        </button>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search conversations..."
            className="w-full pl-9 pr-3 py-2 bg-muted border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto divide-y divide-border">
        {filteredConversations.length === 0 ? (
          <div className="p-4 text-center text-sm text-muted-foreground">
            {searchQuery ? 'No conversations found' : 'No conversations yet'}
          </div>
        ) : (
          filteredConversations.map((conv) => (
            <div
              key={conv.id}
              role="button"
              tabIndex={0}
              onClick={() => setCurrentConversation(conv.id)}
              onKeyDown={(e) => e.key === 'Enter' && setCurrentConversation(conv.id)}
              className={`w-full p-3 text-left hover:bg-muted transition-colors group cursor-pointer ${
                currentConversationId === conv.id ? 'bg-muted' : ''
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate text-sm">
                    {conv.title}
                  </div>
                  <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                    <Calendar className="w-3 h-3" />
                    <span>
                      {formatDistanceToNow(new Date(conv.updated_at), { addSuffix: true })}
                    </span>
                    <span>·</span>
                    <span>{conv.messages.length} msg</span>
                  </div>
                  {conv.messages.length > 0 && (
                    <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                      {conv.messages[conv.messages.length - 1].content}
                    </div>
                  )}
                </div>
                <button
                  onClick={(e) => handleDelete(conv.id, e)}
                  className="opacity-0 group-hover:opacity-100 p-1 hover:bg-destructive/10 rounded transition-opacity"
                  title="Delete conversation"
                >
                  <Trash2 className="w-4 h-4 text-destructive" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Footer Stats */}
      <div className="p-3 border-t border-border text-xs text-muted-foreground text-center">
        {conversations.length} conversation{conversations.length !== 1 ? 's' : ''} total
      </div>
    </div>
  )
}
