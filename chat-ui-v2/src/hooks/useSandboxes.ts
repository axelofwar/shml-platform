/**
 * useSandboxes - Polling hook for NemoClaw sandbox lifecycle
 *
 * Features:
 * - Polls GET /api/nemoclaw/sandbox every 10 seconds (role-gated)
 * - Subscribes to WebSocket SANDBOX_* events from agent-service
 * - Appends live stdout/stderr lines to sandbox store
 * - Surfaces policy violation and approval events
 */

import { useEffect, useRef, useCallback } from 'react'
import { useSandboxStore, type SandboxEntry, type PolicyViolation } from '@/stores/sandboxStore'
import { useAuthStore } from '@/stores/authStore'

// Roles that are allowed to view/manage sandboxes
const SANDBOX_ALLOWED_ROLES = new Set(['elevated-developer', 'admin'])

// Polling interval (ms)
const POLL_INTERVAL_MS = 10_000

// Agent-service WebSocket base URL (same host as the UI, via Traefik)
function getWsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/api/agent/ws/sandbox`
}

interface UseSandboxesOptions {
  /** Pass down from useAgentWebSocket lastJsonMessage if you want to share the socket */
  externalWsMessage?: { type: string; data: unknown } | null
  /** Disable polling entirely (default false) */
  disabled?: boolean
}

export function useSandboxes({ externalWsMessage, disabled = false }: UseSandboxesOptions = {}) {
  const { user } = useAuthStore()
  const {
    setSandboxes,
    updateSandbox,
    appendOutput,
    removeSandbox,
    addViolation,
    setApprovalPending,
    setLoading,
    setError,
    setLastRefreshed,
  } = useSandboxStore()

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  const isAllowed = user && SANDBOX_ALLOWED_ROLES.has(user.primary_role)

  // Fetch sandbox list from factory API (proxied through Traefik → OAuth2-Proxy → role-auth)
  const fetchSandboxes = useCallback(async () => {
    if (!isAllowed || disabled) return

    try {
      setLoading(true)
      const res = await fetch('/api/nemoclaw/sandbox', {
        credentials: 'include',
        headers: { 'Accept': 'application/json' },
      })

      if (res.status === 401 || res.status === 403) {
        // Not authorized — stop polling silently
        if (pollingRef.current) clearInterval(pollingRef.current)
        return
      }

      if (!res.ok) {
        throw new Error(`Factory returned ${res.status}: ${res.statusText}`)
      }

      const raw: SandboxEntry[] = await res.json()
      setSandboxes(raw)
      setError(null)
      setLastRefreshed(new Date().toISOString())
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      // Factory offline is fine (alpha software)
      setError(`NemoClaw factory unavailable: ${msg}`)
    } finally {
      setLoading(false)
    }
  }, [isAllowed, disabled, setSandboxes, setError, setLoading, setLastRefreshed])

  // Connect dedicated WebSocket for sandbox events
  const connectWs = useCallback(() => {
    if (!isAllowed || disabled) return
    if (wsRef.current && wsRef.current.readyState < 2) return // already open/connecting

    const ws = new WebSocket(getWsUrl())
    wsRef.current = ws

    ws.addEventListener('message', (evt) => {
      let msg: { type: string; data: unknown }
      try { msg = JSON.parse(evt.data) } catch { return }
      handleWsMessage(msg)
    })

    ws.addEventListener('close', () => {
      // Reconnect after 5 s if still mounted
      setTimeout(() => {
        if (wsRef.current === ws) connectWs()
      }, 5_000)
    })

    ws.addEventListener('error', () => ws.close())
  }, [isAllowed, disabled]) // eslint-disable-line react-hooks/exhaustive-deps

  // Handle a WebSocket message from the agent-service sandbox channel
  function handleWsMessage(msg: { type: string; data: unknown }) {
    const d = msg.data as Record<string, unknown>

    switch (msg.type) {
      case 'sandbox_created':
        fetchSandboxes()
        break

      case 'sandbox_destroyed':
        if (typeof d.name === 'string') removeSandbox(d.name)
        break

      case 'sandbox_status':
        if (typeof d.name === 'string') {
          updateSandbox(d.name, {
            status: d.status as SandboxEntry['status'],
          })
        }
        break

      case 'sandbox_output':
        if (typeof d.name === 'string' && typeof d.line === 'string') {
          appendOutput(d.name, d.line)
        }
        break

      case 'sandbox_policy_violation':
        if (typeof d.sandbox_name === 'string') {
          addViolation(d.sandbox_name, {
            id: String(d.id ?? crypto.randomUUID()),
            type: (d.violation_type ?? 'filesystem') as PolicyViolation['type'],
            path: typeof d.path === 'string' ? d.path : undefined,
            destination: typeof d.destination === 'string' ? d.destination : undefined,
            syscall: typeof d.syscall === 'string' ? d.syscall : undefined,
            timestamp: typeof d.timestamp === 'string' ? d.timestamp : new Date().toISOString(),
            resolved: false,
          })
        }
        break

      case 'sandbox_approval_request':
        if (typeof d.sandbox_name === 'string') {
          setApprovalPending(d.sandbox_name, {
            tool: String(d.tool ?? ''),
            params: (d.params as Record<string, unknown>) ?? {},
            requested_at: String(d.requested_at ?? new Date().toISOString()),
          })
        }
        break

      default:
        break
    }
  }

  // Handle externally-shared WebSocket messages (e.g., from useAgentWebSocket)
  useEffect(() => {
    if (!externalWsMessage) return
    handleWsMessage(externalWsMessage)
  }, [externalWsMessage]) // eslint-disable-line react-hooks/exhaustive-deps

  // Start polling + WebSocket on mount
  useEffect(() => {
    if (!isAllowed || disabled) return

    fetchSandboxes()
    pollingRef.current = setInterval(fetchSandboxes, POLL_INTERVAL_MS)
    connectWs()

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
      if (wsRef.current) {
        const ws = wsRef.current
        wsRef.current = null
        ws.close()
      }
    }
  }, [isAllowed, disabled]) // eslint-disable-line react-hooks/exhaustive-deps

  // Expose manual refresh
  return { refresh: fetchSandboxes }
}

/** Approve a pending operator-approval request */
export async function approveSandboxRequest(sandboxName: string): Promise<void> {
  const res = await fetch(`/api/nemoclaw/sandbox/${encodeURIComponent(sandboxName)}/approve`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Approve failed: ${res.statusText}`)
}

/** Deny a pending operator-approval request */
export async function denySandboxRequest(sandboxName: string): Promise<void> {
  const res = await fetch(`/api/nemoclaw/sandbox/${encodeURIComponent(sandboxName)}/deny`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Deny failed: ${res.statusText}`)
}

/** Destroy a sandbox by name */
export async function destroySandbox(sandboxName: string): Promise<void> {
  const res = await fetch(`/api/nemoclaw/sandbox/${encodeURIComponent(sandboxName)}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Destroy failed: ${res.statusText}`)
}
