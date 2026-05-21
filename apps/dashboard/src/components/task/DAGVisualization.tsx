'use client'

import { Subtask } from '@/lib/api'
import { AgentBadge } from '@/components/ui/AgentBadge'
import { StatusBadge } from '@/components/ui/StatusBadge'
import clsx from 'clsx'

interface Props {
  subtasks: Subtask[]
}

const NODE_COLORS: Record<string, { border: string; bg: string }> = {
  pending:   { border: 'border-gray-600',        bg: 'bg-gray-800/50' },
  queued:    { border: 'border-blue-500/50',      bg: 'bg-blue-900/20' },
  running:   { border: 'border-amber-500/60',     bg: 'bg-amber-900/20' },
  retrying:  { border: 'border-orange-500/60',    bg: 'bg-orange-900/20' },
  completed: { border: 'border-emerald-500/50',   bg: 'bg-emerald-900/20' },
  failed:    { border: 'border-red-500/50',       bg: 'bg-red-900/20' },
  dlq:       { border: 'border-red-700/60',       bg: 'bg-red-950/30' },
  cancelled: { border: 'border-gray-700',         bg: 'bg-gray-900/30' },
}

/**
 * Simple vertical DAG visualization.
 * For a task with linear dependencies (most common case), this renders
 * as a top-to-bottom pipeline. Parallel subtasks sit side by side.
 *
 * A proper force-directed graph (e.g. d3-dag, react-flow) would be better
 * for arbitrary DAG topologies — tracked as a v2 enhancement.
 */
export function DAGVisualization({ subtasks }: Props) {
  if (subtasks.length === 0) {
    return (
      <div className="text-center py-8 text-gray-600 font-mono text-xs">
        Awaiting task planning...
      </div>
    )
  }

  // Build level-based layout: level 0 = no deps, level N = max(dep levels)+1
  const levelMap = computeLevels(subtasks)
  const maxLevel = Math.max(...Object.values(levelMap))
  const byLevel: Record<number, Subtask[]> = {}
  for (const [id, level] of Object.entries(levelMap)) {
    if (!byLevel[level]) byLevel[level] = []
    const st = subtasks.find(s => s.id === id)
    if (st) byLevel[level].push(st)
  }

  return (
    <div className="space-y-3">
      {Array.from({ length: maxLevel + 1 }, (_, lvl) => (
        <div key={lvl}>
          {/* Level label */}
          <div className="text-xs text-gray-600 font-mono mb-2">
            {lvl === 0 ? 'Start' : `Step ${lvl}`}
          </div>

          {/* Connector line from previous level */}
          {lvl > 0 && (
            <div className="flex justify-center mb-2">
              <div className="w-px h-4 bg-border" />
            </div>
          )}

          {/* Nodes at this level */}
          <div className={clsx(
            'flex gap-2',
            (byLevel[lvl]?.length || 0) > 1 ? 'justify-center' : 'justify-start'
          )}>
            {(byLevel[lvl] || []).map(st => {
              const colors = NODE_COLORS[st.status] || NODE_COLORS.pending
              const isRunning = st.status === 'running' || st.status === 'retrying'

              return (
                <div
                  key={st.id}
                  className={clsx(
                    'dag-node border flex-1 max-w-xs',
                    colors.border, colors.bg,
                    isRunning && 'animate-pulse-slow'
                  )}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <AgentBadge agentType={st.agent_type} size="sm" />
                    <StatusBadge status={st.status} />
                  </div>
                  <div className="text-xs text-gray-300 font-medium truncate">
                    {st.name}
                  </div>
                  {st.retry_count > 0 && (
                    <div className="text-xs text-accent-amber font-mono mt-0.5">
                      retry ×{st.retry_count}
                    </div>
                  )}
                  {st.tokens_used > 0 && (
                    <div className="text-xs text-gray-600 font-mono mt-0.5">
                      {st.tokens_used.toLocaleString()} tokens
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {/* Terminal indicator */}
      {subtasks.every(s => s.status === 'completed') && (
        <div className="flex justify-center">
          <div className="w-px h-4 bg-accent-emerald/30" />
        </div>
      )}
      <div className="text-xs text-gray-600 font-mono text-center">
        {subtasks.filter(s => s.status === 'completed').length}/{subtasks.length} complete
      </div>
    </div>
  )
}

function computeLevels(subtasks: Subtask[]): Record<string, number> {
  const idToSubtask = new Map(subtasks.map(s => [s.id, s]))
  const levels: Record<string, number> = {}

  function getLevel(id: string): number {
    if (id in levels) return levels[id]
    const st = idToSubtask.get(id)
    if (!st || !st.depends_on?.length) {
      levels[id] = 0
      return 0
    }
    const maxDepLevel = Math.max(...st.depends_on.map(d => getLevel(d)))
    levels[id] = maxDepLevel + 1
    return levels[id]
  }

  subtasks.forEach(s => getLevel(s.id))
  return levels
}
