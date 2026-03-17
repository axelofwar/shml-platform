/**
 * SandboxesPanel - NemoClaw OpenShell sandbox management UI
 *
 * Features:
 * - Lists active sandboxes with status, role, blueprint, violation counts
 * - Per-sandbox live stdout/stderr log viewer
 * - Policy violation details with "Request Approval" / "Deny" workflow
 * - Destroy sandbox button (admin / elevated-developer only)
 * - Auto-refreshes via useSandboxes hook (poll + WebSocket)
 * - Hidden for roles below elevated-developer
 */

import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Shield,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Trash2,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  AlertTriangle,
  Cpu,
  Lock,
  Unlock,
  Radio,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useSandboxStore, type SandboxEntry, type PolicyViolation } from '@/stores/sandboxStore'
import { useAuthStore } from '@/stores/authStore'
import {
  useSandboxes,
  approveSandboxRequest,
  denySandboxRequest,
  destroySandbox,
} from '@/hooks/useSandboxes'
import { toast } from 'sonner'

// ─── Status badge ────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<SandboxEntry['status'], { label: string; className: string; icon: React.ReactNode }> = {
  creating: {
    label: 'Creating',
    className: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    icon: <Radio className="w-3 h-3 animate-pulse" />,
  },
  running: {
    label: 'Running',
    className: 'bg-green-500/20 text-green-300 border-green-500/30',
    icon: <ShieldCheck className="w-3 h-3" />,
  },
  policy_blocked: {
    label: 'Policy Blocked',
    className: 'bg-red-500/20 text-red-400 border-red-500/30',
    icon: <ShieldAlert className="w-3 h-3 animate-pulse" />,
  },
  destroyed: {
    label: 'Destroyed',
    className: 'bg-zinc-600/30 text-zinc-500 border-zinc-600/30',
    icon: <XCircle className="w-3 h-3" />,
  },
  error: {
    label: 'Error',
    className: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    icon: <AlertTriangle className="w-3 h-3" />,
  },
}

const BLUEPRINT_COLORS: Record<string, string> = {
  viewer: 'text-zinc-400',
  developer: 'text-sky-400',
  elevated: 'text-violet-400',
  admin: 'text-amber-400',
}

// ─── Violation item ───────────────────────────────────────────────────────────

function ViolationBadge({ v }: { v: PolicyViolation }) {
  const label =
    v.type === 'filesystem'
      ? `FS: ${v.path ?? 'unknown'}`
      : v.type === 'network_egress'
      ? `Net: ${v.destination ?? 'unknown'}`
      : `Syscall: ${v.syscall ?? 'unknown'}`

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 px-2 py-0.5 rounded text-xs border font-mono',
        v.resolved
          ? 'bg-green-500/10 text-green-400 border-green-500/20 line-through opacity-60'
          : 'bg-red-500/10 text-red-400 border-red-500/20'
      )}
      title={new Date(v.timestamp).toLocaleString()}
    >
      {v.resolved ? <CheckCircle2 className="w-3 h-3" /> : <Lock className="w-3 h-3" />}
      {label}
    </div>
  )
}

// ─── Live output viewer ───────────────────────────────────────────────────────

function LiveOutput({ lines, onClear }: { lines: string[]; onClear: () => void }) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines.length])

  return (
    <div className="relative mt-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-zinc-500 uppercase tracking-wider">Live Output</span>
        <button
          onClick={onClear}
          className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          Clear
        </button>
      </div>
      <div className="bg-black/60 border border-zinc-800 rounded font-mono text-[11px] text-green-400 p-2 h-40 overflow-y-auto">
        {lines.length === 0 && (
          <span className="text-zinc-600 italic">No output yet…</span>
        )}
        {lines.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

// ─── Per-sandbox card ─────────────────────────────────────────────────────────

function SandboxCard({
  sandbox,
  isSelected,
  onSelect,
  canDestroy,
}: {
  sandbox: SandboxEntry
  isSelected: boolean
  onSelect: () => void
  canDestroy: boolean
}) {
  const { clearOutput } = useSandboxStore()
  const activeViolations = sandbox.violations.filter((v) => !v.resolved)
  const statusInfo = STATUS_STYLES[sandbox.status] ?? STATUS_STYLES.error

  const [isApproving, setIsApproving] = useState(false)
  const [isDenying, setIsDenying] = useState(false)
  const [isDestroying, setIsDestroying] = useState(false)

  const handleApprove = async (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsApproving(true)
    try {
      await approveSandboxRequest(sandbox.name)
      toast.success(`Approved request for ${sandbox.name}`)
    } catch (err) {
      toast.error(String(err))
    } finally {
      setIsApproving(false)
    }
  }

  const handleDeny = async (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsDenying(true)
    try {
      await denySandboxRequest(sandbox.name)
      toast.info(`Denied request for ${sandbox.name}`)
    } catch (err) {
      toast.error(String(err))
    } finally {
      setIsDenying(false)
    }
  }

  const handleDestroy = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Destroy sandbox "${sandbox.name}"? This cannot be undone.`)) return
    setIsDestroying(true)
    try {
      await destroySandbox(sandbox.name)
      toast.success(`Sandbox ${sandbox.name} destroyed`)
    } catch (err) {
      toast.error(String(err))
    } finally {
      setIsDestroying(false)
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className={cn(
        'border rounded-lg overflow-hidden transition-colors cursor-pointer',
        isSelected
          ? 'border-primary/50 bg-primary/5'
          : 'border-border bg-zinc-900/60 hover:bg-zinc-900/80'
      )}
      onClick={onSelect}
    >
      {/* Header row */}
      <div className="flex items-center justify-between px-3 py-2 gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {isSelected ? (
            <ChevronDown className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0" />
          )}
          <span className="font-mono text-xs text-zinc-200 truncate">{sandbox.name}</span>
          {activeViolations.length > 0 && (
            <span className="flex-shrink-0 text-[10px] bg-red-500/20 text-red-400 border border-red-500/30 rounded px-1">
              {activeViolations.length} violation{activeViolations.length > 1 ? 's' : ''}
            </span>
          )}
          {sandbox.pendingApproval && (
            <span className="flex-shrink-0 text-[10px] bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded px-1 animate-pulse">
              Awaiting approval
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Blueprint badge */}
          <span className={cn('text-[10px] font-mono', BLUEPRINT_COLORS[sandbox.blueprint] ?? 'text-zinc-400')}>
            {sandbox.blueprint}
          </span>

          {/* Status badge */}
          <span
            className={cn(
              'flex items-center gap-1 text-[10px] border rounded px-1.5 py-0.5',
              statusInfo.className
            )}
          >
            {statusInfo.icon}
            {statusInfo.label}
          </span>

          {/* Destroy button */}
          {canDestroy && sandbox.status !== 'destroyed' && (
            <button
              onClick={handleDestroy}
              disabled={isDestroying}
              className="p-1 rounded hover:bg-red-500/20 text-zinc-500 hover:text-red-400 transition-colors"
              title="Destroy sandbox"
            >
              {isDestroying ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Trash2 className="w-3.5 h-3.5" />
              )}
            </button>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      <AnimatePresence initial={false}>
        {isSelected && (
          <motion.div
            key="detail"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-2 border-t border-border/50">
              {/* Metadata row */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 pt-2 text-[11px] text-zinc-500">
                <div>
                  <span className="text-zinc-600">Owner: </span>
                  <span className="text-zinc-400">{sandbox.owner_user}</span>
                </div>
                <div>
                  <span className="text-zinc-600">Created: </span>
                  <span className="text-zinc-400">
                    {new Date(sandbox.created_at).toLocaleTimeString()}
                  </span>
                </div>
                {sandbox.inference_profile && (
                  <div className="col-span-2">
                    <span className="text-zinc-600">Inference: </span>
                    <span className="text-sky-400 font-mono">{sandbox.inference_profile}</span>
                  </div>
                )}
              </div>

              {/* Policy violations */}
              {sandbox.violations.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Policy Violations</p>
                  <div className="flex flex-wrap gap-1">
                    {sandbox.violations.map((v) => (
                      <ViolationBadge key={v.id} v={v} />
                    ))}
                  </div>
                </div>
              )}

              {/* Operator approval */}
              {sandbox.pendingApproval && sandbox.approvalRequest && (
                <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2 space-y-2">
                  <div className="flex items-center gap-2">
                    <Unlock className="w-3.5 h-3.5 text-amber-400" />
                    <span className="text-xs text-amber-300 font-medium">Operator Approval Required</span>
                  </div>
                  <p className="text-[11px] text-zinc-400">
                    Tool: <span className="text-zinc-200 font-mono">{sandbox.approvalRequest.tool}</span>
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={handleApprove}
                      disabled={isApproving}
                      className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] bg-green-600/20 border border-green-600/40 text-green-400 rounded hover:bg-green-600/30 transition-colors disabled:opacity-50"
                    >
                      {isApproving ? (
                        <RefreshCw className="w-3 h-3 animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-3 h-3" />
                      )}
                      Approve
                    </button>
                    <button
                      onClick={handleDeny}
                      disabled={isDenying}
                      className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] bg-red-600/20 border border-red-600/40 text-red-400 rounded hover:bg-red-600/30 transition-colors disabled:opacity-50"
                    >
                      {isDenying ? (
                        <RefreshCw className="w-3 h-3 animate-spin" />
                      ) : (
                        <XCircle className="w-3 h-3" />
                      )}
                      Deny
                    </button>
                  </div>
                </div>
              )}

              {/* Live output */}
              <LiveOutput
                lines={sandbox.liveOutput}
                onClear={() => clearOutput(sandbox.name)}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// ─── Main panel ───────────────────────────────────────────────────────────────

interface SandboxesPanelProps {
  className?: string
}

export function SandboxesPanel({ className }: SandboxesPanelProps) {
  const { user } = useAuthStore()
  const {
    sandboxes,
    isSandboxPanelOpen,
    setSandboxPanelOpen,
    selectedSandbox,
    selectSandbox,
    isLoading,
    error,
    lastRefreshed,
  } = useSandboxStore()

  const { refresh } = useSandboxes()

  const isAdmin = user?.primary_role === 'admin'
  const canAccess =
    user?.primary_role === 'elevated-developer' || user?.primary_role === 'admin'

  // Don't render for roles without access
  if (!canAccess) return null

  const entries = Object.values(sandboxes)
  const activeSandboxes = entries.filter((s) => s.status !== 'destroyed')
  const totalViolations = entries.reduce((sum, s) => sum + s.violations.filter((v) => !v.resolved).length, 0)
  const pendingApprovals = entries.filter((s) => s.pendingApproval).length

  return (
    <>
      {/* ── Trigger button (fixed in header area via ChatLayout) ── */}
      {/* This component is mounted always when canAccess; the button is rendered inline */}

      {/* ── Sandboxes slide-over panel ── */}
      <AnimatePresence>
        {isSandboxPanelOpen && (
          <>
            {/* Backdrop */}
            <motion.div
              key="backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-40 bg-black/40"
              onClick={() => setSandboxPanelOpen(false)}
            />

            {/* Panel */}
            <motion.div
              key="panel"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 28, stiffness: 300 }}
              className={cn(
                'fixed right-0 top-0 bottom-0 z-50 w-full max-w-md',
                'bg-zinc-950 border-l border-border shadow-2xl flex flex-col',
                className
              )}
            >
              {/* Panel header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-violet-400" />
                  <span className="font-semibold text-sm">NemoClaw Sandboxes</span>
                  {activeSandboxes.length > 0 && (
                    <span className="text-[10px] bg-zinc-800 text-zinc-400 border border-zinc-700 rounded px-1.5 py-0.5">
                      {activeSandboxes.length} active
                    </span>
                  )}
                  {totalViolations > 0 && (
                    <span className="text-[10px] bg-red-500/20 text-red-400 border border-red-500/30 rounded px-1.5 py-0.5">
                      {totalViolations} violation{totalViolations > 1 ? 's' : ''}
                    </span>
                  )}
                  {pendingApprovals > 0 && (
                    <span className="text-[10px] bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded px-1.5 py-0.5 animate-pulse">
                      {pendingApprovals} pending
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={refresh}
                    disabled={isLoading}
                    className="p-1.5 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-300 transition-colors"
                    title="Refresh"
                  >
                    <RefreshCw className={cn('w-3.5 h-3.5', isLoading && 'animate-spin')} />
                  </button>
                  <button
                    onClick={() => setSandboxPanelOpen(false)}
                    className="p-1.5 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-300 transition-colors"
                    title="Close"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Error banner */}
              {error && (
                <div className="mx-4 mt-3 px-3 py-2 bg-orange-500/10 border border-orange-500/20 rounded text-[11px] text-orange-400 flex items-start gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}

              {/* Sandbox list */}
              <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
                {isLoading && entries.length === 0 && (
                  <div className="flex flex-col items-center justify-center py-12 text-zinc-600">
                    <RefreshCw className="w-6 h-6 animate-spin mb-2" />
                    <span className="text-sm">Loading sandboxes…</span>
                  </div>
                )}

                {!isLoading && entries.length === 0 && (
                  <div className="flex flex-col items-center justify-center py-12 text-zinc-600">
                    <Terminal className="w-8 h-8 mb-3 opacity-40" />
                    <p className="text-sm font-medium">No active sandboxes</p>
                    <p className="text-xs mt-1 text-center max-w-xs">
                      Sandboxes are created when an agent executes code via the OpenShellSkill.
                    </p>
                  </div>
                )}

                <AnimatePresence>
                  {entries.map((sandbox) => (
                    <SandboxCard
                      key={sandbox.name}
                      sandbox={sandbox}
                      isSelected={selectedSandbox === sandbox.name}
                      onSelect={() =>
                        selectSandbox(selectedSandbox === sandbox.name ? null : sandbox.name)
                      }
                      canDestroy={isAdmin}
                    />
                  ))}
                </AnimatePresence>
              </div>

              {/* Footer */}
              <div className="px-4 py-2 border-t border-border flex items-center justify-between">
                <div className="flex items-center gap-2 text-[10px] text-zinc-600">
                  <Cpu className="w-3 h-3" />
                  <span>OpenShell · Landlock + seccomp + netns</span>
                </div>
                {lastRefreshed && (
                  <span className="text-[10px] text-zinc-700">
                    {new Date(lastRefreshed).toLocaleTimeString()}
                  </span>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

// ─── Trigger button (exported separately so ChatLayout can embed it) ───────────

export function SandboxesTriggerButton() {
  const { user } = useAuthStore()
  const { isSandboxPanelOpen, toggleSandboxPanel, sandboxes } = useSandboxStore()

  const canAccess =
    user?.primary_role === 'elevated-developer' || user?.primary_role === 'admin'

  if (!canAccess) return null

  const entries = Object.values(sandboxes)
  const activeCount = entries.filter((s) => s.status !== 'destroyed').length
  const hasViolations = entries.some((s) => s.violations.some((v) => !v.resolved))
  const hasPending = entries.some((s) => s.pendingApproval)

  return (
    <button
      onClick={toggleSandboxPanel}
      className={cn(
        'relative flex items-center gap-1.5 px-2 sm:px-3 py-1.5 rounded-lg transition-colors text-sm border',
        isSandboxPanelOpen
          ? 'bg-violet-600/20 border-violet-500/40 text-violet-300'
          : 'bg-muted/50 border-border text-muted-foreground hover:bg-muted'
      )}
      title="NemoClaw Sandboxes (⌘S)"
    >
      {hasViolations || hasPending ? (
        <ShieldAlert className={cn('w-4 h-4', hasPending ? 'text-amber-400' : 'text-red-400')} />
      ) : (
        <Shield className="w-4 h-4" />
      )}
      <span className="hidden sm:inline">Sandboxes</span>
      {activeCount > 0 && (
        <span className="flex items-center justify-center w-4 h-4 text-[9px] bg-violet-500/30 border border-violet-500/40 text-violet-300 rounded-full font-bold">
          {activeCount}
        </span>
      )}
      {(hasViolations || hasPending) && (
        <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-red-500 border border-background" />
      )}
    </button>
  )
}
