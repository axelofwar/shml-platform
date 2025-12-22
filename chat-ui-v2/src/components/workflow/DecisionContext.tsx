/**
 * DecisionContext - Display agent reasoning, rubric scores, and tool execution
 *
 * Shows:
 * - Generator proposal and reasoning
 * - Reflector rubric scores (clarity, completeness, correctness, actionability)
 * - Tool execution timeline
 * - Curator lessons learned
 * - Usage instructions
 */

import { useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle, AlertCircle, Loader2, Lightbulb } from 'lucide-react'

interface RubricScores {
  clarity: number
  completeness: number
  correctness: number
  actionability: number
}

interface ToolExecution {
  tool: string
  status: 'pending' | 'running' | 'success' | 'error'
  duration?: number
  summary?: string
  output?: string
}

interface DecisionContextProps {
  generatorReasoning?: string
  rubricScores?: RubricScores
  toolExecutions?: ToolExecution[]
  lessonsLearned?: string[]
  usageInstructions?: string[]
}

export function DecisionContext({
  generatorReasoning,
  rubricScores,
  toolExecutions,
  lessonsLearned,
  usageInstructions
}: DecisionContextProps) {
  const [isExpanded, setIsExpanded] = useState(true)

  // Don't render if no data
  if (!generatorReasoning && !rubricScores && !toolExecutions && !lessonsLearned && !usageInstructions) {
    return null
  }

  const overallScore = rubricScores
    ? (rubricScores.clarity + rubricScores.completeness + rubricScores.correctness + rubricScores.actionability) / 4
    : 0

  return (
    <div className="bg-muted/50 rounded-lg overflow-hidden">
      {/* Header - Collapsible */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-muted/70 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          <span className="font-semibold">🧠 Agent Reasoning</span>
          {rubricScores && (
            <span className={`text-xs px-2 py-0.5 rounded ${
              overallScore >= 0.8 ? 'bg-green-500/10 text-green-400' :
              overallScore >= 0.6 ? 'bg-yellow-500/10 text-yellow-400' :
              'bg-red-500/10 text-red-400'
            }`}>
              Overall: {(overallScore * 100).toFixed(0)}%
            </span>
          )}
        </div>
        <span className="text-xs text-muted-foreground">
          {isExpanded ? 'Hide details' : 'Show details'}
        </span>
      </button>

      {/* Content */}
      {isExpanded && (
        <div className="p-4 space-y-4 border-t border-border">
          {/* Generator Reasoning */}
          {generatorReasoning && (
            <div>
              <div className="text-sm font-medium mb-2">Generator Proposal</div>
              <div className="text-xs text-muted-foreground whitespace-pre-wrap">
                {generatorReasoning}
              </div>
            </div>
          )}

          {/* Rubric Scores */}
          {rubricScores && (
            <div>
              <div className="text-sm font-medium mb-2">Reflector Analysis</div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <MetricBadge label="Clarity" score={rubricScores.clarity} />
                <MetricBadge label="Complete" score={rubricScores.completeness} />
                <MetricBadge label="Correct" score={rubricScores.correctness} />
                <MetricBadge label="Actionable" score={rubricScores.actionability} />
              </div>
              <div className="text-xs text-muted-foreground mt-2 flex items-center gap-2">
                {overallScore >= 0.7 ? (
                  <>
                    <CheckCircle className="w-3 h-3 text-green-400" />
                    <span>Approved for execution</span>
                  </>
                ) : (
                  <>
                    <AlertCircle className="w-3 h-3 text-yellow-400" />
                    <span>Needs refinement</span>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Tool Execution Timeline */}
          {toolExecutions && toolExecutions.length > 0 && (
            <div>
              <div className="text-sm font-medium mb-2">Tool Execution</div>
              <div className="space-y-2">
                {toolExecutions.map((tool, i) => (
                  <div key={i} className="border-l-2 border-blue-500 pl-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{tool.tool}</span>
                      <StatusBadge status={tool.status} />
                      {tool.duration && (
                        <span className="text-xs text-muted-foreground ml-auto">
                          {tool.duration}ms
                        </span>
                      )}
                    </div>
                    {tool.summary && (
                      <div className="text-xs text-muted-foreground mt-1">
                        {tool.summary}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Lessons Learned */}
          {lessonsLearned && lessonsLearned.length > 0 && (
            <div>
              <div className="text-sm font-medium mb-2">Lessons Learned</div>
              <ul className="text-xs text-muted-foreground space-y-1">
                {lessonsLearned.map((lesson, i) => (
                  <li key={i}>• {lesson}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Usage Instructions */}
          {usageInstructions && usageInstructions.length > 0 && (
            <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3">
              <div className="flex items-center gap-2 font-semibold text-blue-400 mb-2">
                <Lightbulb className="w-4 h-4" />
                <span>How to Use This</span>
              </div>
              <div className="text-xs text-muted-foreground space-y-1">
                {usageInstructions.map((instruction, i) => (
                  <div key={i}>• {instruction}</div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MetricBadge({ label, score }: { label: string; score: number }) {
  const getColor = (s: number) => {
    if (s >= 0.8) return 'green'
    if (s >= 0.6) return 'yellow'
    return 'red'
  }

  const color = getColor(score)

  return (
    <div className={`text-center p-2 rounded bg-${color}-500/10 border border-${color}-500/20`}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-sm font-bold text-${color}-400`}>
        {(score * 100).toFixed(0)}%
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const configs: Record<string, { bg: string; text: string; icon: typeof Loader2; spin: boolean }> = {
    pending: { bg: 'bg-gray-500/10', text: 'text-gray-400', icon: Loader2, spin: false },
    running: { bg: 'bg-blue-500/10', text: 'text-blue-400', icon: Loader2, spin: true },
    success: { bg: 'bg-green-500/10', text: 'text-green-400', icon: CheckCircle, spin: false },
    error: { bg: 'bg-red-500/10', text: 'text-red-400', icon: AlertCircle, spin: false },
  }

  const config = configs[status] || configs.pending
  const Icon = config.icon

  return (
    <span className={`text-xs px-2 py-0.5 rounded ${config.bg} ${config.text} flex items-center gap-1`}>
      <Icon className={`w-3 h-3 ${config.spin ? 'animate-spin' : ''}`} />
      {status}
    </span>
  )
}
