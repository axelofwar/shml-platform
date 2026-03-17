/**
 * MessageContent - Renders message content with proper markdown formatting
 * Handles code blocks with syntax highlighting, markdown text, and decision context
 */

import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { DecisionContext } from '@/components/workflow/DecisionContext'
import type { DecisionContext as DecisionContextType } from '@/stores/chatStore'

interface MessageContentProps {
  content: string
  className?: string
  decisionContext?: DecisionContextType
  showDecisionContext?: boolean
}

export function MessageContent({
  content,
  className = '',
  decisionContext,
  showDecisionContext = true
}: MessageContentProps) {
  return (
    <div className={className}>
      {/* Decision Context (agent reasoning) - shown above content */}
      {showDecisionContext && decisionContext && (
        <div className="mb-3">
          <DecisionContext
            generatorReasoning={decisionContext.generatorReasoning}
            rubricScores={decisionContext.rubricScores}
            toolExecutions={decisionContext.toolExecutions}
            lessonsLearned={decisionContext.lessonsLearned}
            usageInstructions={decisionContext.usageInstructions}
          />
        </div>
      )}

      {/* Main content with markdown */}
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const language = match ? match[1] : 'plaintext'
            const isInline = !match && !String(children).includes('\n')

            return !isInline ? (
              <div className="my-3 rounded-lg overflow-hidden border border-gray-700">
                <div className="px-4 py-2 bg-gray-800 text-xs text-gray-400 border-b border-gray-700 font-mono">
                  {language}
                </div>
                <SyntaxHighlighter
                  style={vscDarkPlus}
                  language={language}
                  PreTag="div"
                  className="!m-0 !p-4 !bg-[#1e1e1e]"
                  customStyle={{
                    margin: 0,
                    borderRadius: 0,
                    fontSize: '0.875rem',
                  }}
                >
                  {String(children).replace(/\n$/, '')}
                </SyntaxHighlighter>
              </div>
            ) : (
              <code className="px-1.5 py-0.5 bg-gray-800 text-gray-300 rounded text-sm font-mono" {...props}>
                {children}
              </code>
            )
          },
          p({ children }) {
            return <p className="mb-2 last:mb-0">{children}</p>
          },
          strong({ children }) {
            return <strong className="font-bold text-foreground">{children}</strong>
          },
          em({ children }) {
            return <em className="italic">{children}</em>
          },
          ul({ children }) {
            return <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>
          },
          ol({ children }) {
            return <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>
          },
          li({ children }) {
            return <li className="ml-2">{children}</li>
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
