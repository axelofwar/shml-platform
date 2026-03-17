/**
 * ChatInterface - Main chat UI component
 *
 * Integrates:
 * - WebSocket connection
 * - Message display
 * - Input field
 * - ACE workflow state
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useAgentWebSocket, MessageType } from '@/hooks/useAgentWebSocket'
import { useChatStore } from '@/stores/chatStore'
import { useWorkflowStore } from '@/stores/workflowStore'
import { useUIStore } from '@/stores/uiStore'
import { MessageContent } from './MessageContent'
import { AttachmentButton, AttachmentBadges, AttachmentFile } from './AttachmentButton'
import { Send, Loader2, Bot, User } from 'lucide-react'

export function ChatInterface() {
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<AttachmentFile[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const completionProcessedRef = useRef<string | null>(null)

  // Pending message to send when connection opens
  const pendingMessageRef = useRef<Record<string, any> | null>(null)

  // Track stage outputs and tool results to build final response
  const [stageOutputs, setStageOutputs] = useState<{ [key: string]: string }>({})
  const [toolResults, setToolResults] = useState<Array<{tool: string, result: any}>>([])
  const [hasCompletedWorkflow, setHasCompletedWorkflow] = useState(false)

  // Get current conversation or create new one
  const {
    currentConversationId,
    conversations,
    createConversation,
    addMessage,
    isStreaming,
    setIsStreaming
  } = useChatStore()

  // Ensure we have a conversation
  useEffect(() => {
    if (!currentConversationId) {
      createConversation('New Chat')
    }
  }, [currentConversationId, createConversation])

  const currentConversation = currentConversationId ? conversations[currentConversationId] : null
  const messages = currentConversation?.messages || []

  // Workflow state
  const {
    isActive: isWorkflowActive,
    currentStage,
    startWorkflow,
    setStage,
    updateStageStatus,
    endWorkflow
  } = useWorkflowStore()

  // Get workflow panel state from store (needed early for useEffect dependencies)
  const { workflowPanelHeight, isWorkflowPanelOpen, toggleWorkflowPanel } = useUIStore()

  // Ref to store sendRaw function so we can use it in onConnect callback
  const sendRawRef = useRef<((msg: Record<string, any>) => void) | null>(null)

  // Callback when WebSocket connects - send any pending message
  const handleConnect = useCallback(() => {
    console.log('🔗 WebSocket connected, checking for pending message...')
    if (pendingMessageRef.current && sendRawRef.current) {
      console.log('📤 Sending pending message:', pendingMessageRef.current.type)
      // Small delay to ensure readyState is OPEN (1) before sending
      setTimeout(() => {
        if (sendRawRef.current && pendingMessageRef.current) {
          sendRawRef.current(pendingMessageRef.current)
          console.log('✅ Pending message sent')
          pendingMessageRef.current = null
        }
      }, 50)
    }
  }, [])

  // WebSocket connection - use conversation ID as base session
  // Each message will get its own sub-session to avoid DB conflicts
  const baseSessionId = currentConversationId || 'temp-session'
  const hookReturn = useAgentWebSocket({
    sessionId: baseSessionId,
    enabled: true,
    autoConnect: true, // Let the hook handle connection
    onConnect: handleConnect,
    // Heartbeat keeps connection alive during long workflows
    heartbeatIntervalMs: 15000, // Send heartbeat every 15 seconds
    heartbeatTimeoutMs: 10000, // Wait 10 seconds for ACK before considering connection dead
  })

  const {
    isConnected,
    connectionState,
    connect,
    disconnect,
    sendMessage: sendWSMessage,
    sendRaw,
    lastMessage,
  } = hookReturn

  // Keep sendRaw ref up to date
  useEffect(() => {
    sendRawRef.current = sendRaw
  }, [sendRaw])

  // Handle incoming WebSocket messages
  useEffect(() => {
    if (!lastMessage) return

    // The actual message structure from agent-service:
    // {"type":"stage_output","stage":"generator","content":"..."}
    // NOT {type: "...", data: {...}}
    const msg = lastMessage as any // Use any to access actual properties
    const msgType = msg.type

    console.log('📨 Message:', msgType, 'stage:', msg.stage, 'content:', msg.content?.substring(0, 50))

    // Handle different message types based on actual structure
    switch (msgType) {
      case 'stage_output':
        // This is stage progress output
        if (!isWorkflowActive && msg.stage) {
          console.log('🚀 Starting workflow for stage:', msg.stage)
          startWorkflow(baseSessionId)
          // Auto-open workflow panel when workflow starts
          if (!isWorkflowPanelOpen) {
            toggleWorkflowPanel()
          }
          // Clear stage outputs and tool results for new workflow
          setStageOutputs({})
          setToolResults([])
          setHasCompletedWorkflow(false)
        }
        if (msg.stage) {
          console.log('▶️ Stage running:', msg.stage)
          // Complete previous stage when new one starts
          if (isWorkflowActive && currentStage !== msg.stage && currentStage !== 'idle') {
            console.log('✅ Completing previous stage:', currentStage)
            updateStageStatus(currentStage, {
              status: 'completed',
              completed_at: new Date().toISOString()
            })
          }
          setStage(msg.stage)

          // Accumulate stage outputs (for vision, generator, and curator)
          if ((msg.stage === 'vision' || msg.stage === 'generator' || msg.stage === 'curator') && msg.content) {
            const stage = msg.stage as string
            console.log(`📝 Accumulating ${stage} output:`, msg.content.substring(0, 50))
            setStageOutputs(prev => {
              const updated: { [key: string]: string } = {
                ...prev,
                [stage]: (prev[stage] || '') + msg.content
              }
              console.log(`💾 Updated stageOutputs for ${stage}, length:`, updated[stage]?.length)
              return updated
            })
          }
        }
        break

      case 'stage_complete':
        // Stage finished (if backend sends this)
        if (msg.stage) {
          console.log('✅ Stage complete:', msg.stage)
          updateStageStatus(msg.stage, {
            status: 'completed',
            completed_at: new Date().toISOString()
          })
        }
        break

      case 'complete':
        // Prevent duplicate completion handling using ref (survives StrictMode)
        const completionId = `${currentConversationId}-${msg.execution_time_ms}`
        if (completionProcessedRef.current === completionId) {
          console.log('⚠️ Ignoring duplicate complete message:', completionId)
          break
        }
        completionProcessedRef.current = completionId

        // Workflow complete with final output
        const executionTime = msg.execution_time_ms ? `${(msg.execution_time_ms / 1000).toFixed(2)}s` : 'unknown'
        const lessonsCount = msg.lessons_count || 0
        console.log('🏁 Workflow complete:', executionTime, 'lessons:', lessonsCount)
        setIsStreaming(false)
        setHasCompletedWorkflow(true)

        // Mark current stage as complete
        if (currentStage !== 'idle' && currentStage !== 'complete') {
          console.log('✅ Marking final stage complete:', currentStage)
          updateStageStatus(currentStage, {
            status: 'completed',
            completed_at: new Date().toISOString()
          })
        }

        // End the workflow
        endWorkflow()

        // Show completion message in chat using tool results and stage outputs
        if (currentConversationId) {
          console.log('📦 Stage outputs:', stageOutputs)
          console.log('🔧 Tool results:', toolResults)

          let finalOutput = ''

          // If we have sandbox execution results, show the output
          const sandboxResult = toolResults.find(t => t.tool === 'SandboxSkill')
          if (sandboxResult && sandboxResult.result) {
            console.log('🔍 Sandbox result structure:', sandboxResult.result)
            const res = sandboxResult.result

            // The result might be stringified JSON or direct object
            let parsedResult = res
            if (typeof res === 'string') {
              try {
                parsedResult = JSON.parse(res)
              } catch (e) {
                parsedResult = { stdout: res }
              }
            }

            // Extract the code from generator output to show alongside results
            let codeBlock = ''
            const generatorOutput = stageOutputs.generator || ''
            console.log('📄 Full generator output length:', generatorOutput.length)

            // Try multiple patterns to find Python code
            // Pattern 1: Code in markdown block
            let codeMatch = generatorOutput.match(/```python\n([\s\S]+?)\n```/)
            if (codeMatch) {
              console.log('✅ Found code in markdown block')
            }

            if (!codeMatch) {
              // Pattern 2: Code in Tool params ("code": "...")
              // This needs to handle escaped quotes and newlines
              const toolMatch = generatorOutput.match(/"code":\s*"((?:[^"\\]|\\.)*)"/s)
              if (toolMatch && toolMatch[1]) {
                console.log('✅ Found code in Tool params, length:', toolMatch[1].length)
                // Unescape the JSON string
                const unescapedCode = toolMatch[1]
                  .replace(/\\n/g, '\n')
                  .replace(/\\"/g, '"')
                  .replace(/\\\\/g, '\\')
                  .replace(/\\t/g, '\t')
                codeMatch = ['', unescapedCode]
              } else {
                console.log('❌ No code found in generator output')
              }
            }

            if (codeMatch && codeMatch[1]) {
              codeBlock = '```python\n' + codeMatch[1].trim() + '\n```\n\n'
              console.log('📝 Code block created, length:', codeBlock.length)
            }

            // Build clean response: code + output
            finalOutput = codeBlock

            if (parsedResult.stdout && parsedResult.stdout.trim()) {
              finalOutput += '**Output:**\n```\n' + parsedResult.stdout.trim() + '\n```'
            }
            if (parsedResult.stderr && parsedResult.stderr.trim()) {
              finalOutput += '\n\n**Errors:**\n```\n' + parsedResult.stderr.trim() + '\n```'
            }

            console.log('✅ Using sandbox result as final output')
          } else {
            // SOTA Pattern: Use generator output (the actual response to user)
            // Curator contains lessons learned for the system, not user-facing content
            // Priority: generator (main response) > curator (fallback for edge cases)
            finalOutput = stageOutputs.generator || stageOutputs.curator || 'Task completed successfully!'
            finalOutput = finalOutput.replace(/^Generator starting\.\.\.Generator starting\.\.\./g, '').trim()
            finalOutput = finalOutput.replace(/^Generator starting\.\.\./, '').trim()
            finalOutput = finalOutput.replace(/^Extracting lessons learned\.\.\./, '').trim()
            console.log('📝 Using generator output (primary response)')

            /*
            // DISABLE SMART EXTRACTION - It was causing truncated outputs
            // The LLM output is usually well-structured enough to display fully

            // Unescape JSON escape sequences (\n, \", \\, etc.)
            finalOutput = finalOutput
              .replace(/\\n/g, '\n')
              .replace(/\\t/g, '\t')
              .replace(/\\"/g, '"')
              .replace(/\\\\/g, '\\')

            // Smart extraction: Look for Implementation, Code, Solution sections first
            let extracted = null

            // Pattern 1: Look for **Implementation:** or **Code:** sections
            const implMatch = finalOutput.match(/\*\*(?:Implementation|Code|Solution)\*\*:?\s*(.+?)(?:\*\*[A-Z]|$)/s)
            if (implMatch && implMatch[1]) {
              extracted = implMatch[1].trim()
            }

            // Pattern 2: Extract code blocks (```...```)
            if (!extracted || extracted.length < 100) {
              const codeBlocks = finalOutput.match(/```[\w]*\n([\s\S]+?)```/g)
              if (codeBlocks && codeBlocks.length > 0) {
                // Combine all code blocks
                extracted = codeBlocks.join('\n\n')
              }
            }

            // Pattern 3: Fallback to Action section (for non-code tasks)
            if (!extracted) {
              const actionMatch = finalOutput.match(/\*\*Action\*\*:(.+?)(?:\*\*Expected Outcome\*\*:|Tool:|$)/s)
              if (actionMatch && actionMatch[1]) {
                extracted = actionMatch[1].trim()
              }
            }

            // Use extracted content if found, otherwise use full output
            if (extracted) {
              finalOutput = extracted
            }
            */

            console.log('📝 Using full generator output')
          }

          console.log('✉️ Final output length:', finalOutput.length)

          // Only add message if we have content
          if (finalOutput.trim()) {
            addMessage(currentConversationId, {
              id: `msg-${Date.now()}`,
              role: 'assistant',
              content: finalOutput,
              timestamp: new Date().toISOString(),
            })
          }

          // Clear for next message
          setStageOutputs({})
          setToolResults([])
        }
        break

      case 'tool_result':
        // Tool execution result - properties are at root level, not in data
        const tool = msg.tool || 'unknown'
        const operation = msg.operation || 'unknown'
        const success = msg.success !== undefined ? msg.success : false
        const result = msg.result
        console.log('🔧 Tool result:', tool, operation, 'success:', success, 'result:', result)

        // Store tool results - especially sandbox code execution results
        if (success && result) {
          setToolResults(prev => [...prev, { tool, result }])
          console.log('💾 Stored tool result from:', tool)
        }
        break

      case 'error':
        // Error occurred
        const errorMsg = msg.message || msg.error || 'Unknown error'
        console.log('❌ Error:', errorMsg)
        setIsStreaming(false)
        if (currentConversationId) {
          addMessage(currentConversationId, {
            id: `msg-${Date.now()}`,
            role: 'assistant',
            content: `Error: ${errorMsg}`,
            timestamp: new Date().toISOString(),
          })
        }
        break

      default:
        console.log('❓ Unknown message type:', msgType, msg)
    }
  }, [lastMessage, currentConversationId, baseSessionId, isWorkflowActive, currentStage, addMessage, setIsStreaming, startWorkflow, setStage, updateStageStatus, endWorkflow])

  // Auto-scroll to bottom when new messages arrive or workflow panel height changes
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, workflowPanelHeight, isWorkflowPanelOpen])

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [input])

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return

    const userMessage = input.trim()
    setInput('')

    // Add user message to chat
    if (currentConversationId) {
      addMessage(currentConversationId, {
        id: `msg-${Date.now()}`,
        role: 'user',
        content: userMessage,
        timestamp: new Date().toISOString(),
      })
    }

    // Send to agent via WebSocket
    // Start a fresh workflow for each message
    console.log('🚀 Sending new message, starting fresh workflow')
    if (isWorkflowActive) {
      endWorkflow()
    }

    // Clear stage outputs and tool results for new request
    setStageOutputs({})
    setToolResults([])
    setHasCompletedWorkflow(false)
    completionProcessedRef.current = null

    setIsStreaming(true)
    // Generate unique session ID for this request to avoid DB conflicts
    const messageSessionId = `${baseSessionId}-${Date.now()}`
    console.log('📤 Message session:', messageSessionId)
    console.log('📡 WebSocket state:', { isConnected, connectionState })

    // Process attachments to base64
    const processedAttachments = await Promise.all(
      attachments.map(async (attachment) => {
        return new Promise<any>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => {
            const base64 = (reader.result as string).split(',')[1] // Remove data:image/png;base64, prefix
            resolve({
              id: attachment.id,
              filename: attachment.file.name,
              type: attachment.type,
              mime_type: attachment.file.type,
              size: attachment.file.size,
              data: base64,
            })
          }
          reader.onerror = reject
          reader.readAsDataURL(attachment.file)
        })
      })
    )

    console.log(`📎 Processed ${processedAttachments.length} attachments`)

    // Build the agent request message
    const agentRequest: any = {
      type: 'agent_request',
      user_id: 'demo-user',
      session_id: messageSessionId,
      task: userMessage,
      category: 'general',
      timestamp: new Date().toISOString(),
    }

    // Include attachments if present
    if (processedAttachments.length > 0) {
      agentRequest.attachments = processedAttachments
      console.log('📎 Including attachments in request:', processedAttachments.map(a => ({
        filename: a.filename,
        type: a.type,
        size: a.size,
      })))
    }

    // Clear attachments after sending
    setAttachments([])

    // Agent-service now supports multiple requests per connection with heartbeats
    if (isConnected) {
      console.log('📦 Agent request:', { ...agentRequest, attachments: agentRequest.attachments?.map((a: any) => ({ ...a, data: `${a.data.slice(0, 20)}...` })) })
      sendRaw(agentRequest)
      console.log('✅ Sent agent_request')
    } else {
      // Not connected - store message and connect
      console.log('🔌 Not connected, storing message and connecting...')
      pendingMessageRef.current = agentRequest
      connect()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      handleSend()
    }
  }

  // Calculate dynamic padding based on panel state
  // Account for: workflow panel + input area (~120px) + buffer (32px)
  const inputAreaHeight = 120
  const bottomPadding = isWorkflowPanelOpen
    ? workflowPanelHeight + inputAreaHeight + 32
    : inputAreaHeight + 32

  return (
    <div className="flex flex-col h-full">
      {/* Messages area - add padding at bottom for workflow panel */}
      <div
        className="flex-1 overflow-y-auto px-4 py-6 space-y-4"
        style={{ paddingBottom: `${bottomPadding}px` }}
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
            <Bot className="w-16 h-16 text-muted-foreground/50" />
            <div>
              <h2 className="text-xl font-semibold mb-2">Start a conversation</h2>
              <p className="text-muted-foreground">
                Ask me anything and watch the ACE workflow in action
              </p>
            </div>
            <div className="flex gap-2 flex-wrap justify-center max-w-2xl">
              <button
                onClick={() => {
                  setInput('Write a Python function to calculate fibonacci numbers')
                  setTimeout(() => textareaRef.current?.focus(), 100)
                }}
                className="px-4 py-2 bg-muted hover:bg-muted/80 rounded-lg text-sm transition-colors"
              >
                Write Python code
              </button>
              <button
                onClick={() => {
                  setInput('Explain the difference between async and sync programming')
                  setTimeout(() => textareaRef.current?.focus(), 100)
                }}
                className="px-4 py-2 bg-muted hover:bg-muted/80 rounded-lg text-sm transition-colors"
              >
                Explain a concept
              </button>
              <button
                onClick={() => {
                  setInput('Help me debug this error: TypeError: undefined is not a function')
                  setTimeout(() => textareaRef.current?.focus(), 100)
                }}
                className="px-4 py-2 bg-muted hover:bg-muted/80 rounded-lg text-sm transition-colors"
              >
                Debug an error
              </button>
            </div>
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                {message.role === 'assistant' && (
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                    <Bot className="w-5 h-5 text-primary" />
                  </div>
                )}
                <div
                  className={`max-w-[70%] rounded-lg px-4 py-3 ${
                    message.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted'
                  }`}
                >
                  <MessageContent content={message.content} className="text-sm" />
                  <p className="text-xs opacity-70 mt-2">
                    {new Date(message.timestamp).toLocaleTimeString()}
                  </p>
                </div>
                {message.role === 'user' && (
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-500/10 flex items-center justify-center">
                    <User className="w-5 h-5 text-blue-400" />
                  </div>
                )}
              </div>
            ))}
            {isStreaming && (
              <div className="flex gap-3 justify-start">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                  <Bot className="w-5 h-5 text-primary" />
                </div>
                <div className="bg-muted rounded-lg px-4 py-3">
                  <div className="flex items-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm text-muted-foreground">
                      {isWorkflowActive ? `${currentStage} stage...` : 'Thinking...'}
                    </span>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input area - Always visible, positioned above workflow panel */}
      <div
        className="border-t border-border px-4 py-4 bg-background fixed left-0 right-0 z-40"
        style={{ bottom: `${isWorkflowPanelOpen ? workflowPanelHeight : 0}px` }}
      >
        {/* Attachment badges */}
        {attachments.length > 0 && (
          <div className="max-w-4xl mx-auto mb-2">
            <AttachmentBadges
              attachments={attachments}
              onRemove={(id) => setAttachments(prev => prev.filter(a => a.id !== id))}
            />
          </div>
        )}

        <div className="flex gap-2 items-end max-w-4xl mx-auto">
          {/* Attachment button */}
          <AttachmentButton
            attachments={attachments}
            onAttachmentsChange={setAttachments}
            disabled={!isConnected || isStreaming}
            maxFiles={5}
          />

          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isConnected ? 'Type a message... (Ctrl+Enter to send)' : 'Connecting...'}
              disabled={!isConnected || isStreaming}
              rows={1}
              className="w-full px-4 py-3 bg-background border-2 border-border rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed max-h-32 text-foreground"
            />
          </div>
          <button
            onClick={handleSend}
            disabled={!input.trim() || !isConnected || isStreaming}
            className="p-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title="Send message (Ctrl+Enter)"
          >
            {isStreaming ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>

        {/* Status bar */}
        <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground max-w-4xl mx-auto">
          <div className="flex items-center gap-4">
            <span className={`flex items-center gap-1 ${isConnected ? 'text-green-400' : 'text-red-400'}`}>
              <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400' : 'bg-red-400'}`} />
              {isConnected ? 'Connected' : 'Disconnected'}
            </span>
            {isWorkflowActive && (
              <span className="text-blue-400 flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                ACE workflow active
              </span>
            )}
          </div>
          <span>Press Ctrl+Enter to send</span>
        </div>
      </div>
    </div>
  )
}
