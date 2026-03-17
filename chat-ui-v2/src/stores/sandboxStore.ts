/**
 * Sandbox Store - Manages NemoClaw OpenShell sandbox state
 *
 * Tracks active sandboxes, policy violations, approval requests,
 * and live sandbox output streamed from the factory server.
 */

import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

export type SandboxStatus = 'creating' | 'running' | 'policy_blocked' | 'destroyed' | 'error'
export type SandboxBlueprint = 'viewer' | 'developer' | 'elevated' | 'admin'

export interface PolicyViolation {
  id: string
  type: 'filesystem' | 'network_egress' | 'syscall'
  path?: string
  destination?: string
  syscall?: string
  timestamp: string
  resolved: boolean
}

export interface SandboxEntry {
  name: string
  status: SandboxStatus
  blueprint: SandboxBlueprint
  owner_role: string
  owner_user: string
  created_at: string
  inference_profile?: string
  violations: PolicyViolation[]
  // Live stdout/stderr captured via WebSocket or SSE
  liveOutput: string[]
  // Pending operator approval
  pendingApproval: boolean
  approvalRequest?: {
    tool: string
    params: Record<string, unknown>
    requested_at: string
  }
}

interface SandboxStore {
  // Sandbox map: name → entry
  sandboxes: Record<string, SandboxEntry>

  // UI state
  isSandboxPanelOpen: boolean
  selectedSandbox: string | null
  isLoading: boolean
  error: string | null
  lastRefreshed: string | null

  // Actions
  toggleSandboxPanel: () => void
  setSandboxPanelOpen: (open: boolean) => void
  selectSandbox: (name: string | null) => void

  // Data actions
  setSandboxes: (sandboxes: SandboxEntry[]) => void
  updateSandbox: (name: string, patch: Partial<SandboxEntry>) => void
  appendOutput: (name: string, line: string) => void
  clearOutput: (name: string) => void
  removeSandbox: (name: string) => void
  addViolation: (sandboxName: string, violation: PolicyViolation) => void
  resolveViolation: (sandboxName: string, violationId: string) => void
  setApprovalPending: (sandboxName: string, request?: SandboxEntry['approvalRequest']) => void

  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  setLastRefreshed: (ts: string) => void
}

export const useSandboxStore = create<SandboxStore>()(
  immer((set) => ({
    sandboxes: {},
    isSandboxPanelOpen: false,
    selectedSandbox: null,
    isLoading: false,
    error: null,
    lastRefreshed: null,

    toggleSandboxPanel: () =>
      set((state) => { state.isSandboxPanelOpen = !state.isSandboxPanelOpen }),

    setSandboxPanelOpen: (open) =>
      set((state) => { state.isSandboxPanelOpen = open }),

    selectSandbox: (name) =>
      set((state) => { state.selectedSandbox = name }),

    setSandboxes: (entries) =>
      set((state) => {
        const next: Record<string, SandboxEntry> = {}
        for (const e of entries) {
          // Preserve liveOutput and local-only fields when refreshing
          const existing = state.sandboxes[e.name]
          next[e.name] = {
            ...e,
            liveOutput: existing?.liveOutput ?? [],
            violations: existing?.violations ?? e.violations ?? [],
          }
        }
        state.sandboxes = next
      }),

    updateSandbox: (name, patch) =>
      set((state) => {
        if (state.sandboxes[name]) {
          Object.assign(state.sandboxes[name], patch)
        }
      }),

    appendOutput: (name, line) =>
      set((state) => {
        if (state.sandboxes[name]) {
          // Keep last 500 lines
          const out = state.sandboxes[name].liveOutput
          out.push(line)
          if (out.length > 500) out.splice(0, out.length - 500)
        }
      }),

    clearOutput: (name) =>
      set((state) => {
        if (state.sandboxes[name]) state.sandboxes[name].liveOutput = []
      }),

    removeSandbox: (name) =>
      set((state) => {
        delete state.sandboxes[name]
        if (state.selectedSandbox === name) state.selectedSandbox = null
      }),

    addViolation: (sandboxName, violation) =>
      set((state) => {
        if (state.sandboxes[sandboxName]) {
          state.sandboxes[sandboxName].violations.push(violation)
          state.sandboxes[sandboxName].status = 'policy_blocked'
        }
      }),

    resolveViolation: (sandboxName, violationId) =>
      set((state) => {
        const sb = state.sandboxes[sandboxName]
        if (sb) {
          const v = sb.violations.find((x) => x.id === violationId)
          if (v) v.resolved = true
          // If all resolved, restore running status
          if (sb.violations.every((x) => x.resolved)) sb.status = 'running'
        }
      }),

    setApprovalPending: (sandboxName, request) =>
      set((state) => {
        const sb = state.sandboxes[sandboxName]
        if (sb) {
          sb.pendingApproval = !!request
          sb.approvalRequest = request
        }
      }),

    setLoading: (loading) =>
      set((state) => { state.isLoading = loading }),

    setError: (error) =>
      set((state) => { state.error = error }),

    setLastRefreshed: (ts) =>
      set((state) => { state.lastRefreshed = ts }),
  }))
)
