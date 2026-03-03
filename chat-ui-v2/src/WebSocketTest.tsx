import { useEffect, useState } from 'react'
import { useAgentWebSocket, MessageType, ConnectionState } from './hooks/useAgentWebSocket'

export function WebSocketTest() {
  // Use a stable session ID (don't regenerate on every render)
  const [sessionId] = useState(() => 'test-session-' + Date.now())

  const {
    connectionState,
    isConnected,
    sendMessage,
    lastMessage,
    messageHistory,
    connect,
    disconnect,
  } = useAgentWebSocket({
    sessionId,
    enabled: true,
    autoConnect: false, // Disable auto-connect to prevent loops
    onConnect: () => {
      console.log('✅ WebSocket Connected!')
    },
    onDisconnect: () => {
      console.log('❌ WebSocket Disconnected')
    },
    onMessage: (msg) => {
      console.log('📨 Received message:', msg)
    },
    onError: (error) => {
      console.error('❌ WebSocket error:', error)
    },
  })

  // Log connection state changes
  useEffect(() => {
    console.log('🔌 Connection state:', connectionState)
  }, [connectionState])

  // Send test heartbeat every 10 seconds when connected
  useEffect(() => {
    if (!isConnected) return

    const interval = setInterval(() => {
      console.log('💓 Sending heartbeat...')
      sendMessage(MessageType.HEARTBEAT, { ping: Date.now() })
    }, 10000)

    return () => clearInterval(interval)
  }, [isConnected, sendMessage])

  return (
    <div className="p-8 space-y-4">
      <h2 className="text-2xl font-bold">WebSocket Connection Test</h2>

      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <span className="font-semibold">Connection State:</span>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${
            connectionState === ConnectionState.CONNECTED
              ? 'bg-green-500/20 text-green-300'
              : connectionState === ConnectionState.CONNECTING || connectionState === ConnectionState.RECONNECTING
              ? 'bg-yellow-500/20 text-yellow-300'
              : 'bg-red-500/20 text-red-300'
          }`}>
            {connectionState}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <span className="font-semibold">Is Connected:</span>
          <span className={isConnected ? 'text-green-300' : 'text-red-300'}>
            {isConnected ? '✓ Yes' : '✗ No'}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <span className="font-semibold">Messages Received:</span>
          <span className="text-blue-300">{messageHistory.length}</span>
        </div>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => connect()}
          disabled={isConnected}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg font-medium"
        >
          Connect
        </button>
        <button
          onClick={() => disconnect()}
          disabled={!isConnected}
          className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg font-medium"
        >
          Disconnect
        </button>
        <button
          onClick={() => sendMessage(MessageType.HEARTBEAT, { ping: Date.now() })}
          disabled={!isConnected}
          className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg font-medium"
        >
          Send Heartbeat
        </button>
      </div>

      <div className="mt-6">
        <h3 className="text-lg font-semibold mb-2">Last Message:</h3>
        <pre className="p-4 bg-gray-900 rounded-lg overflow-auto max-h-40 text-sm">
          {lastMessage ? JSON.stringify(lastMessage, null, 2) : 'No messages yet'}
        </pre>
      </div>

      <div className="mt-4">
        <h3 className="text-lg font-semibold mb-2">Message History ({messageHistory.length}):</h3>
        <div className="space-y-2 max-h-60 overflow-auto">
          {messageHistory.slice().reverse().map((msg, idx) => (
            <div key={idx} className="p-3 bg-gray-900 rounded-lg text-sm">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-semibold text-blue-300">{msg.type}</span>
                <span className="text-gray-500 text-xs">{new Date(msg.timestamp).toLocaleTimeString()}</span>
              </div>
              <pre className="text-xs text-gray-400 overflow-auto">
                {JSON.stringify(msg.data, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 p-4 bg-yellow-900/20 border border-yellow-700 rounded-lg">
        <h3 className="font-semibold text-yellow-300 mb-2">⚠️ Current Status:</h3>
        <div className="space-y-2 text-sm text-gray-300">
          <p className="font-medium text-yellow-200">WebSocket requires OAuth authentication</p>
          <p>The agent-service WebSocket endpoint at <code className="px-1 py-0.5 bg-gray-800 rounded">/api/agent/ws/agent/{'{'}session_id{'}'}</code> is protected by OAuth2-Proxy.</p>
          <p className="mt-2 text-yellow-300 font-medium">Options to test:</p>
          <ol className="list-decimal list-inside space-y-1 ml-4">
            <li>Add unprotected test endpoint to agent-service</li>
            <li>Configure OAuth2-Proxy bypass for WebSocket paths</li>
            <li>Login to FusionAuth first, then test here</li>
          </ol>
        </div>
      </div>

      <div className="mt-4 p-4 bg-blue-900/20 border border-blue-700 rounded-lg">
        <h3 className="font-semibold text-blue-300 mb-2">Test Instructions (Once Connected):</h3>
        <ol className="list-decimal list-inside space-y-1 text-sm text-gray-300">
          <li>Click "Connect" button to initiate connection</li>
          <li>Watch browser console for detailed logs</li>
          <li>Send manual heartbeat with "Send Heartbeat" button</li>
          <li>Test manual disconnect/reconnect buttons</li>
          <li>Check if auto-reconnection works after disconnect</li>
          <li>Verify message history accumulates correctly</li>
        </ol>
      </div>
    </div>
  )
}
