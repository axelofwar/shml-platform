/**
 * MetricsPanel - Recharts visualizations for workflow metrics
 *
 * Features:
 * - Token usage over time (line chart)
 * - Tool usage distribution (pie chart)
 * - Stage duration breakdown (bar chart)
 * - Summary statistics
 */

import { useMemo } from 'react'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { motion } from 'framer-motion'
import { cn } from '../../lib/utils'
import { useWorkflowStore, ACEStage, WorkflowMetrics } from '../../stores/workflowStore'
import { useChatStore, useCurrentMessages } from '../../stores/chatStore'
import { calculateTokenBudget } from '../../lib/tokenBudget'
import {
  Activity,
  Coins,
  Clock,
  Wrench,
  CheckCircle2,
  TrendingUp,
} from 'lucide-react'

// Chart colors
const COLORS = {
  primary: '#3b82f6',    // blue-500
  secondary: '#8b5cf6',  // purple-500
  success: '#22c55e',    // green-500
  warning: '#f59e0b',    // amber-500
  error: '#ef4444',      // red-500
  muted: '#6b7280',      // gray-500
}

const PIE_COLORS = [
  '#3b82f6', // blue
  '#8b5cf6', // purple
  '#22c55e', // green
  '#f59e0b', // amber
  '#ef4444', // red
  '#06b6d4', // cyan
]

interface StatCardProps {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string | number
  subValue?: string
  color: string
}

function StatCard({ icon: Icon, label, value, subValue, color }: StatCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-background border rounded-lg p-4"
    >
      <div className="flex items-center gap-2 mb-2">
        <div className={cn('p-2 rounded-lg', `bg-${color}/10`)}>
          <Icon className={cn('w-4 h-4', `text-${color}`)} />
        </div>
        <span className="text-sm text-muted-foreground">{label}</span>
      </div>
      <p className="text-2xl font-bold">{value}</p>
      {subValue && (
        <p className="text-xs text-muted-foreground mt-1">{subValue}</p>
      )}
    </motion.div>
  )
}

interface MetricsPanelProps {
  className?: string
  compact?: boolean
}

export function MetricsPanel({ className, compact = false }: MetricsPanelProps) {
  const { metrics, tools, toolExecutionOrder, stages } = useWorkflowStore()
  const messages = useCurrentMessages()

  // Calculate token budget
  const tokenBudget = useMemo(() => {
    return calculateTokenBudget(messages)
  }, [messages])

  // Prepare tool usage data for pie chart
  const toolUsageData = useMemo(() => {
    const toolCounts: Record<string, number> = {}
    toolExecutionOrder.forEach((id) => {
      const tool = tools[id]
      if (tool) {
        const name = tool.name.split('_')[0] // Group by tool type
        toolCounts[name] = (toolCounts[name] || 0) + 1
      }
    })
    return Object.entries(toolCounts).map(([name, count]) => ({
      name,
      value: count,
    }))
  }, [tools, toolExecutionOrder])

  // Prepare stage duration data for bar chart
  const stageDurationData = useMemo(() => {
    const stageOrder: ACEStage[] = [
      ACEStage.GENERATOR,
      ACEStage.TOOLS,
      ACEStage.REFLECTOR,
      ACEStage.CURATOR,
    ]

    return stageOrder
      .filter((stage) => stages[stage]?.duration_ms)
      .map((stage) => ({
        name: stage.charAt(0).toUpperCase() + stage.slice(1),
        duration: Math.round((stages[stage]?.duration_ms || 0) / 1000 * 10) / 10,
      }))
  }, [stages])

  // Prepare token usage over messages (simulated time series)
  const tokenOverTimeData = useMemo(() => {
    let cumulative = 0
    return messages.slice(-20).map((msg, index) => {
      // Simple token estimation
      const msgTokens = Math.ceil(msg.content.length / 4)
      cumulative += msgTokens
      return {
        message: index + 1,
        tokens: cumulative,
        msgTokens,
      }
    })
  }, [messages])

  // Statistics
  const totalTools = toolExecutionOrder.length
  const successfulTools = Object.values(tools).filter(
    (t) => t.status === 'completed' || t.status === 'approved'
  ).length
  const totalDuration = metrics.total_duration_ms ||
    Object.values(stages).reduce((sum, s) => sum + (s.duration_ms || 0), 0)

  if (compact) {
    // Compact inline stats
    return (
      <div className={cn('flex items-center gap-4 text-sm', className)}>
        <div className="flex items-center gap-1 text-muted-foreground">
          <Coins className="w-4 h-4" />
          <span>{tokenBudget.totalTokens} tokens</span>
        </div>
        <div className="flex items-center gap-1 text-muted-foreground">
          <Wrench className="w-4 h-4" />
          <span>{successfulTools}/{totalTools} tools</span>
        </div>
        <div className="flex items-center gap-1 text-muted-foreground">
          <Clock className="w-4 h-4" />
          <span>{(totalDuration / 1000).toFixed(1)}s</span>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('space-y-6', className)}>
      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          icon={Coins}
          label="Tokens Used"
          value={tokenBudget.totalTokens.toLocaleString()}
          subValue={`${Math.round(tokenBudget.usedPercentage * 100)}% of budget`}
          color="blue-500"
        />
        <StatCard
          icon={Wrench}
          label="Tool Calls"
          value={totalTools}
          subValue={`${successfulTools} successful`}
          color="purple-500"
        />
        <StatCard
          icon={Clock}
          label="Duration"
          value={`${(totalDuration / 1000).toFixed(1)}s`}
          subValue="Total workflow time"
          color="amber-500"
        />
        <StatCard
          icon={Activity}
          label="Messages"
          value={messages.length}
          subValue="In conversation"
          color="green-500"
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Token Usage Over Time */}
        {tokenOverTimeData.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-background border rounded-lg p-4"
          >
            <h3 className="font-medium mb-4 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-blue-500" />
              Token Usage Over Messages
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={tokenOverTimeData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis
                  dataKey="message"
                  stroke="#666"
                  fontSize={12}
                  tickLine={false}
                />
                <YAxis
                  stroke="#666"
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1f2937',
                    border: '1px solid #374151',
                    borderRadius: '8px',
                  }}
                  labelStyle={{ color: '#9ca3af' }}
                />
                <Line
                  type="monotone"
                  dataKey="tokens"
                  stroke={COLORS.primary}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </motion.div>
        )}

        {/* Stage Duration Breakdown */}
        {stageDurationData.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="bg-background border rounded-lg p-4"
          >
            <h3 className="font-medium mb-4 flex items-center gap-2">
              <Clock className="w-4 h-4 text-amber-500" />
              Stage Duration (seconds)
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={stageDurationData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#333" horizontal={false} />
                <XAxis type="number" stroke="#666" fontSize={12} />
                <YAxis
                  type="category"
                  dataKey="name"
                  stroke="#666"
                  fontSize={12}
                  width={80}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1f2937',
                    border: '1px solid #374151',
                    borderRadius: '8px',
                  }}
                  labelStyle={{ color: '#9ca3af' }}
                />
                <Bar
                  dataKey="duration"
                  fill={COLORS.secondary}
                  radius={[0, 4, 4, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </motion.div>
        )}

        {/* Tool Usage Distribution */}
        {toolUsageData.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-background border rounded-lg p-4"
          >
            <h3 className="font-medium mb-4 flex items-center gap-2">
              <Wrench className="w-4 h-4 text-purple-500" />
              Tool Usage Distribution
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={toolUsageData}
                  cx="50%"
                  cy="50%"
                  innerRadius={40}
                  outerRadius={80}
                  paddingAngle={2}
                  dataKey="value"
                  label={({ name, percent }) =>
                    `${name} (${(percent * 100).toFixed(0)}%)`
                  }
                  labelLine={false}
                >
                  {toolUsageData.map((_, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={PIE_COLORS[index % PIE_COLORS.length]}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1f2937',
                    border: '1px solid #374151',
                    borderRadius: '8px',
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </motion.div>
        )}

        {/* Token Breakdown */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="bg-background border rounded-lg p-4"
        >
          <h3 className="font-medium mb-4 flex items-center gap-2">
            <Coins className="w-4 h-4 text-blue-500" />
            Token Breakdown
          </h3>
          <div className="space-y-3">
            {[
              { label: 'System Prompt', value: tokenBudget.breakdown.systemPrompt, color: 'blue' },
              { label: 'User Messages', value: tokenBudget.breakdown.userMessages, color: 'green' },
              { label: 'Assistant', value: tokenBudget.breakdown.assistantMessages, color: 'purple' },
              { label: 'Tool Calls', value: tokenBudget.breakdown.toolCalls, color: 'amber' },
            ].map(({ label, value, color }) => (
              <div key={label}>
                <div className="flex items-center justify-between text-sm mb-1">
                  <span className="text-muted-foreground">{label}</span>
                  <span>{value.toLocaleString()}</span>
                </div>
                <div className="h-2 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className={cn('h-full rounded-full', `bg-${color}-500`)}
                    style={{
                      width: `${Math.min(100, (value / tokenBudget.totalTokens) * 100)}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  )
}

export default MetricsPanel
