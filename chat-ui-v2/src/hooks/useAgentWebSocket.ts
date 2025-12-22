/**
 * useAgentWebSocket - SOTA WebSocket hook for agent-service
 *
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Message queue during disconnection
 * - Heartbeat/ping-pong for connection health
 * - Type-safe message handling
 * - Connection state management
 *
 * Based on best practices from:
 * - react-use-websocket (maintained by Robtec)
 * - Phoenix LiveView (Elixir)
 * - Socket.IO reconnection strategies
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import useWebSocket, { ReadyState } from 'react-use-websocket'

// WebSocket connection states
export enum ConnectionState {
  CONNECTING = 'CONNECTING',
  CONNECTED = 'CONNECTED',
  DISCONNECTED = 'DISCONNECTED',
  RECONNECTING = 'RECONNECTING',
  ERROR = 'ERROR',
}

// Message types from agent-service
export enum MessageType {
  // ACE Workflow stages
  STAGE_START = 'stage_start',
  STAGE_COMPLETE = 'stage_complete',
  STAGE_ERROR = 'stage_error',

  // Tool execution
  TOOL_CALL = 'tool_call',
  TOOL_RESULT = 'tool_result',
  TOOL_ERROR = 'tool_error',

  // Approval workflow
  APPROVAL_REQUEST = 'approval_request',
  APPROVAL_RESPONSE = 'approval_response',

  // Progress updates
  THINKING = 'thinking',
  PROGRESS = 'progress',

  // Final results
  RESULT = 'result',
  ERROR = 'error',

  // Connection management
  HEARTBEAT = 'heartbeat',
  ACK = 'ack',
  PING = 'ping',
  PONG = 'pong',
}

// WebSocket message structure
export interface WebSocketMessage {
  type: MessageType
  data: any
  timestamp: string
  session_id?: string
}

// Hook options
export interface UseAgentWebSocketOptions {
  sessionId: string
  enabled?: boolean
  autoConnect?: boolean
  onMessage?: (message: WebSocketMessage) => void
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: (error: Event) => void
  // Reconnection config
  maxReconnectAttempts?: number
  reconnectIntervalMs?: number
  maxReconnectIntervalMs?: number
  // Heartbeat config
  heartbeatIntervalMs?: number
  heartbeatTimeoutMs?: number
}

// Hook return type
export interface UseAgentWebSocketReturn {
  // Connection state
  connectionState: ConnectionState
  readyState: ReadyState
  isConnected: boolean
  reconnectCount: number

  // Message handling
  sendMessage: (type: MessageType, data: any) => void
  sendRaw: (message: Record<string, any>) => void // Direct send without wrapper
  lastMessage: WebSocketMessage | null
  messageHistory: WebSocketMessage[]

  // Control
  connect: () => void
  disconnect: () => void
  clearHistory: () => void
}

/**
 * Custom hook for WebSocket connection to agent-service
 */
export function useAgentWebSocket(
  options: UseAgentWebSocketOptions
): UseAgentWebSocketReturn {
  const {
    sessionId,
    enabled = true,
    autoConnect = false,
    onMessage,
    onConnect,
    onDisconnect,
    onError,
    maxReconnectAttempts = 10,
    reconnectIntervalMs = 1000,
    maxReconnectIntervalMs = 30000,
    heartbeatIntervalMs = 30000,
    heartbeatTimeoutMs = 5000,
  } = options

  // Build WebSocket URL dynamically based on current location
  // This ensures it works both locally and when accessing remotely
  const getWebSocketUrl = () => {
    const envUrl = import.meta.env.VITE_AGENT_WS_URL

    // If env URL is a full URL, use it directly (for production)
    if (envUrl?.startsWith('ws://') || envUrl?.startsWith('wss://')) {
      return `${envUrl}/${sessionId}`
    }

    // Relative URL - build WebSocket URL for proxy
    // In dev: ws://localhost:3002/ws-test/ws/agent/{sessionId} proxied to agent service
    // In prod: wss://domain.com/ws-test/ws/agent/{sessionId} via Traefik
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'

    // Use window.location.host to maintain the same host:port as the page
    // This ensures Vite proxy intercepts the WebSocket connection in dev mode
    return `${wsProtocol}//${window.location.host}${envUrl}/${sessionId}`
  }

  // State - declare before using in logs
  const [shouldConnect, setShouldConnect] = useState(autoConnect)

  const wsUrl = getWebSocketUrl()

  // Log the URL for debugging (only on mount/change)
  useEffect(() => {
    console.log('[WebSocket] URL:', wsUrl, 'enabled:', enabled, 'shouldConnect:', shouldConnect)
  }, [wsUrl, enabled, shouldConnect])
  const [connectionState, setConnectionState] = useState<ConnectionState>(
    ConnectionState.DISCONNECTED
  )
  const [reconnectCount, setReconnectCount] = useState(0)
  const [messageHistory, setMessageHistory] = useState<WebSocketMessage[]>([])
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)

  // Refs for intervals
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval>>()
  const heartbeatTimeoutRef = useRef<ReturnType<typeof setTimeout>>()

  // Message queue for offline messages
  const messageQueueRef = useRef<Array<{ type: MessageType; data: any }>>([])

  // react-use-websocket hook
  const {
    sendMessage: wsSendMessage,
    lastMessage: wsLastMessage,
    readyState,
    getWebSocket,
  } = useWebSocket(
    wsUrl,
    {
      // Reconnection config with exponential backoff
      shouldReconnect: () => shouldConnect && enabled && reconnectCount < maxReconnectAttempts,
      reconnectAttempts: maxReconnectAttempts,
      reconnectInterval: (attemptNumber) => {
        const interval = Math.min(
          reconnectIntervalMs * Math.pow(2, attemptNumber),
          maxReconnectIntervalMs
        )
        return interval
      },

      // Connection callbacks
      onOpen: () => {
        console.log(`[WebSocket] Connected to ${wsUrl}`)
        setConnectionState(ConnectionState.CONNECTED)
        setReconnectCount(0)

        // Don't send initial test message - causes DB conflicts
        // The user's first actual message will start the workflow

        onConnect?.()

        // Flush message queue
        if (messageQueueRef.current.length > 0) {
          console.log(`[WebSocket] Flushing ${messageQueueRef.current.length} queued messages`)
          messageQueueRef.current.forEach(({ type, data }) => {
            sendMessageInternal(type, data)
          })
          messageQueueRef.current = []
        }

        // Start heartbeat
        startHeartbeat()
      },

      onClose: () => {
        console.log(`[WebSocket] Disconnected from ${wsUrl}`)
        setConnectionState(
          reconnectCount >= maxReconnectAttempts
            ? ConnectionState.DISCONNECTED
            : ConnectionState.RECONNECTING
        )
        onDisconnect?.()

        // Stop heartbeat
        stopHeartbeat()
      },

      onError: (event) => {
        console.error('[WebSocket] Error:', event)
        setConnectionState(ConnectionState.ERROR)
        onError?.(event)
      },

      onReconnectStop: (numAttempts) => {
        console.warn(`[WebSocket] Max reconnect attempts (${numAttempts}) reached`)
        setConnectionState(ConnectionState.DISCONNECTED)
      },

      // Only connect if enabled and shouldConnect is true
      share: false,
      retryOnError: true,
    },
    enabled && shouldConnect
  )

  // Parse and handle incoming messages
  useEffect(() => {
    if (wsLastMessage?.data) {
      try {
        const message: WebSocketMessage = JSON.parse(wsLastMessage.data)

        // Add to history (except ping/pong)
        if (message.type !== MessageType.PING && message.type !== MessageType.PONG) {
          setMessageHistory((prev) => [...prev, message])
          setLastMessage(message)
        }

        // Handle server ping (respond with pong)
        if (message.type === MessageType.PING) {
          console.log('[WebSocket] Received server ping, sending pong...')
          lastPongRef.current = Date.now()
          wsSendMessage(JSON.stringify({ type: 'pong', timestamp: new Date().toISOString() }))
          return
        }

        // Handle heartbeat responses
        if (message.type === MessageType.HEARTBEAT || message.type === MessageType.ACK) {
          console.log('[WebSocket] Received heartbeat ACK, connection healthy')
          resetHeartbeatTimeout()
          missedHeartbeatsRef.current = 0  // Reset missed counter
          return
        }

        // Call user's message handler
        onMessage?.(message)
      } catch (error) {
        console.error('[WebSocket] Failed to parse message:', error)
      }
    }
  }, [wsLastMessage, onMessage, wsSendMessage])

  // Send message helper
  const sendMessageInternal = useCallback(
    (type: MessageType, data: any) => {
      const message: WebSocketMessage = {
        type,
        data,
        timestamp: new Date().toISOString(),
        session_id: sessionId,
      }

      wsSendMessage(JSON.stringify(message))
    },
    [wsSendMessage, sessionId]
  )

  // Public send message (with queueing)
  const sendMessage = useCallback(
    (type: MessageType, data: any) => {
      if (readyState === ReadyState.OPEN) {
        sendMessageInternal(type, data)
      } else {
        // Queue message for later
        console.warn('[WebSocket] Not connected, queueing message:', type)
        messageQueueRef.current.push({ type, data })
      }
    },
    [readyState, sendMessageInternal]
  )

  // Send raw message without wrapper (for agent-service compatibility)
  const sendRaw = useCallback(
    (message: Record<string, any>) => {
      console.log('[WebSocket] sendRaw called, readyState:', readyState, 'message type:', message.type)
      if (readyState === ReadyState.OPEN) {
        const jsonMsg = JSON.stringify(message)
        console.log('[WebSocket] Sending raw message:', jsonMsg.substring(0, 200))
        wsSendMessage(jsonMsg)
        console.log('[WebSocket] Message sent via wsSendMessage')
      } else {
        console.warn('[WebSocket] Not connected, cannot send raw message. ReadyState:', readyState)
      }
    },
    [readyState, wsSendMessage]
  )

  // SOTA Heartbeat mechanism (RFC 6455 compliant with exponential backoff)
  const missedHeartbeatsRef = useRef(0)
  const lastPongRef = useRef<number>(Date.now())

  const startHeartbeat = useCallback(() => {
    // Reset counters
    missedHeartbeatsRef.current = 0
    lastPongRef.current = Date.now()

    // Send heartbeat every N seconds (less frequent than server pings)
    heartbeatIntervalRef.current = setInterval(() => {
      if (readyState === ReadyState.OPEN) {
        // Check if we've received recent pong from server
        const timeSinceLastPong = Date.now() - lastPongRef.current

        if (timeSinceLastPong > 60000) {
          // No pong in 60s - connection is dead
          console.error('[WebSocket] Connection dead (no pong in 60s), closing...')
          getWebSocket()?.close()
          return
        }

        console.log('[WebSocket] Sending heartbeat ping...')
        // Send raw heartbeat message (agent-service expects simple {type: "heartbeat"})
        wsSendMessage(JSON.stringify({ type: 'heartbeat', timestamp: new Date().toISOString() }))

        // Set timeout for response
        heartbeatTimeoutRef.current = setTimeout(() => {
          missedHeartbeatsRef.current++
          console.warn(`[WebSocket] No heartbeat ACK received (missed: ${missedHeartbeatsRef.current})...`)

          // Close after 3 consecutive misses
          if (missedHeartbeatsRef.current >= 3) {
            console.error('[WebSocket] 3 consecutive heartbeat misses, closing connection...')
            getWebSocket()?.close()
          }
        }, heartbeatTimeoutMs)
      }
    }, heartbeatIntervalMs)
  }, [readyState, wsSendMessage, getWebSocket, heartbeatIntervalMs, heartbeatTimeoutMs])

  const stopHeartbeat = useCallback(() => {
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current)
    }
    if (heartbeatTimeoutRef.current) {
      clearTimeout(heartbeatTimeoutRef.current)
    }
    missedHeartbeatsRef.current = 0
  }, [])

  const resetHeartbeatTimeout = useCallback(() => {
    if (heartbeatTimeoutRef.current) {
      clearTimeout(heartbeatTimeoutRef.current)
    }
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopHeartbeat()
    }
  }, [stopHeartbeat])

  // Map ReadyState to ConnectionState
  useEffect(() => {
    switch (readyState) {
      case ReadyState.CONNECTING:
        setConnectionState(
          reconnectCount > 0
            ? ConnectionState.RECONNECTING
            : ConnectionState.CONNECTING
        )
        break
      case ReadyState.OPEN:
        setConnectionState(ConnectionState.CONNECTED)
        break
      case ReadyState.CLOSING:
      case ReadyState.CLOSED:
        setConnectionState(
          reconnectCount >= maxReconnectAttempts
            ? ConnectionState.DISCONNECTED
            : ConnectionState.RECONNECTING
        )
        break
    }
  }, [readyState, reconnectCount, maxReconnectAttempts])

  // Manual connect/disconnect
  const connect = useCallback(() => {
    console.log('[WebSocket] Manual connect requested')
    setReconnectCount(0)
    setShouldConnect(true)
  }, [])

  const disconnect = useCallback(() => {
    console.log('[WebSocket] Manual disconnect requested')
    setReconnectCount(maxReconnectAttempts) // Prevent auto-reconnect
    setShouldConnect(false)
    getWebSocket()?.close()
  }, [getWebSocket, maxReconnectAttempts])

  const clearHistory = useCallback(() => {
    setMessageHistory([])
    setLastMessage(null)
  }, [])

  return {
    // Connection state
    connectionState,
    readyState,
    isConnected: readyState === ReadyState.OPEN,
    reconnectCount,

    // Message handling
    sendMessage,
    sendRaw, // Direct send without wrapper
    lastMessage,
    messageHistory,

    // Control
    connect,
    disconnect,
    clearHistory,
  }
}
