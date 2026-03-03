/**
 * Token Budget Indicator Component
 *
 * Displays real-time token usage with:
 * - Progress bar visualization
 * - Token count and percentage
 * - Status-based colors (green/yellow/orange/red)
 * - Expandable breakdown by category
 *
 * Implements Manus-style context engineering visibility
 */

import React, { useState, useMemo } from 'react'
import { ChevronDown, ChevronUp, AlertTriangle, Info } from 'lucide-react'
import { useCurrentMessages } from '../../stores/chatStore'
import {
  calculateTokenBudget,
  formatTokenCount,
  getTokenBudgetColor,
  getTokenBudgetBgColor,
  getTokenBudgetForRole,
  UserRole,
  TokenBudgetConfig,
} from '../../lib/tokenBudget'

interface TokenBudgetIndicatorProps {
  systemPrompt?: string
  userRole?: UserRole | string  // SOTA: Role-based token budgets
  config?: TokenBudgetConfig    // Override if provided
  showBreakdown?: boolean
  compact?: boolean
}

export const TokenBudgetIndicator: React.FC<TokenBudgetIndicatorProps> = ({
  systemPrompt = '',
  userRole = 'developer',  // Default to developer role
  config,
  showBreakdown = true,
  compact = false,
}) => {
  const messages = useCurrentMessages()
  const [isExpanded, setIsExpanded] = useState(false)

  // SOTA: Get role-based config or use provided override
  const effectiveConfig = useMemo(
    () => config || getTokenBudgetForRole(userRole),
    [config, userRole]
  )

  // Calculate token budget
  const budget = useMemo(
    () => calculateTokenBudget(messages, systemPrompt, effectiveConfig),
    [messages, systemPrompt, effectiveConfig]
  )

  const availableForContext = effectiveConfig.maxContextTokens - effectiveConfig.reservedForResponse
  const percentUsed = Math.min(100, Math.round(budget.usedPercentage * 100))

  // Compact version for header
  if (compact) {
    return (
      <div className="flex items-center gap-2 text-xs">
        <div
          className={`flex items-center gap-1 ${getTokenBudgetColor(budget.status)}`}
          title={`${formatTokenCount(budget.totalTokens)} / ${formatTokenCount(availableForContext)} tokens used`}
        >
          {budget.status === 'warning' || budget.status === 'critical' || budget.status === 'exceeded' ? (
            <AlertTriangle className="w-3 h-3" />
          ) : (
            <Info className="w-3 h-3" />
          )}
          <span>{percentUsed}%</span>
        </div>

        {/* Mini progress bar */}
        <div className="w-16 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-300 ${getTokenBudgetBgColor(budget.status)}`}
            style={{ width: `${Math.min(100, percentUsed)}%` }}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="w-full bg-zinc-800/50 rounded-lg p-3 border border-zinc-700/50">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-zinc-400">Context Budget</span>
          {/* Role badge */}
          {userRole && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-zinc-700/50 text-zinc-400 uppercase">
              {userRole}
            </span>
          )}
          {(budget.status === 'warning' || budget.status === 'critical' || budget.status === 'exceeded') && (
            <AlertTriangle className={`w-3.5 h-3.5 ${getTokenBudgetColor(budget.status)}`} />
          )}
        </div>
        <div className={`text-xs font-medium ${getTokenBudgetColor(budget.status)}`}>
          {formatTokenCount(budget.totalTokens)} / {formatTokenCount(availableForContext)}
        </div>
      </div>

      {/* Progress bar */}
      <div className="w-full h-2 bg-zinc-700 rounded-full overflow-hidden mb-2">
        <div
          className={`h-full transition-all duration-300 ${getTokenBudgetBgColor(budget.status)}`}
          style={{ width: `${Math.min(100, percentUsed)}%` }}
        />
      </div>

      {/* Status message */}
      <div className="flex items-center justify-between text-xs">
        <span className="text-zinc-500">
          {budget.status === 'exceeded' ? (
            'Context limit exceeded - older messages will be summarized'
          ) : budget.status === 'critical' ? (
            'Approaching limit - consider starting a new conversation'
          ) : budget.status === 'warning' ? (
            `${formatTokenCount(budget.availableTokens)} tokens remaining`
          ) : (
            `${formatTokenCount(budget.availableTokens)} tokens available`
          )}
        </span>

        {showBreakdown && (
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 text-zinc-400 hover:text-zinc-300 transition-colors"
          >
            <span>Details</span>
            {isExpanded ? (
              <ChevronUp className="w-3 h-3" />
            ) : (
              <ChevronDown className="w-3 h-3" />
            )}
          </button>
        )}
      </div>

      {/* Expanded breakdown */}
      {showBreakdown && isExpanded && (
        <div className="mt-3 pt-3 border-t border-zinc-700/50 space-y-2">
          <div className="text-xs text-zinc-400 font-medium mb-2">Token Breakdown</div>

          <BreakdownRow
            label="System Prompt"
            tokens={budget.breakdown.systemPrompt}
            total={budget.totalTokens}
            color="bg-blue-500"
          />
          <BreakdownRow
            label="User Messages"
            tokens={budget.breakdown.userMessages}
            total={budget.totalTokens}
            color="bg-purple-500"
          />
          <BreakdownRow
            label="Assistant Responses"
            tokens={budget.breakdown.assistantMessages}
            total={budget.totalTokens}
            color="bg-green-500"
          />
          {budget.breakdown.toolCalls > 0 && (
            <BreakdownRow
              label="Tool Calls"
              tokens={budget.breakdown.toolCalls}
              total={budget.totalTokens}
              color="bg-orange-500"
            />
          )}

          <div className="mt-2 pt-2 border-t border-zinc-700/50 text-xs text-zinc-500">
            <div className="flex justify-between">
              <span>Reserved for response:</span>
              <span>{formatTokenCount(config?.reservedForResponse ?? 0)}</span>
            </div>
            <div className="flex justify-between">
              <span>Total context window:</span>
              <span>{formatTokenCount(config?.maxContextTokens ?? 0)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Breakdown row component
interface BreakdownRowProps {
  label: string
  tokens: number
  total: number
  color: string
}

const BreakdownRow: React.FC<BreakdownRowProps> = ({ label, tokens, total, color }) => {
  const percentage = total > 0 ? Math.round((tokens / total) * 100) : 0

  return (
    <div className="flex items-center gap-2">
      <div className="w-24 text-xs text-zinc-500 truncate">{label}</div>
      <div className="flex-1 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${color}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <div className="w-14 text-xs text-zinc-400 text-right">
        {formatTokenCount(tokens)}
      </div>
    </div>
  )
}

export default TokenBudgetIndicator
