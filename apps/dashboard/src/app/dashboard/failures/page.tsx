'use client'

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { AgentBadge } from '@/components/ui/AgentBadge'
import { AlertTriangle, XCircle, RefreshCw } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import Link from 'next/link'

export default function FailureInspectorPage() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.listTasks(100),
    refetchInterval: 15_000,
  })

  const tasks = data?.tasks || []
  const failedTasks = tasks.filter(t => ['failed', 'dlq', 'cancelled'].includes(t.status))

  // Collect all failed subtasks across all tasks
  const failedSubtasks = tasks.flatMap(t =>
    t.subtasks
      .filter(st => ['failed', 'dlq'].includes(st.status) || st.retry_count > 0)
      .map(st => ({ ...st, taskTitle: t.title, taskId: t.id }))
  )

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Failure Inspector</h1>
          <p className="text-sm text-gray-500 mt-1 font-mono">
            {failedTasks.length} failed tasks · {failedSubtasks.length} failed/retried subtasks
          </p>
        </div>
        <button onClick={() => refetch()} className="btn-ghost flex items-center gap-1.5 text-xs">
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {failedTasks.length === 0 && failedSubtasks.length === 0 && !isLoading ? (
        <div className="card text-center py-16">
          <div className="w-12 h-12 rounded-full bg-accent-emerald/10 border border-accent-emerald/20 flex items-center justify-center mx-auto mb-4">
            <AlertTriangle className="w-5 h-5 text-accent-emerald" />
          </div>
          <h2 className="text-sm font-semibold text-gray-300 mb-1">No Failures</h2>
          <p className="text-xs text-gray-500 font-mono">All tasks completed successfully.</p>
        </div>
      ) : (
        <>
          {/* Failed Tasks */}
          {failedTasks.length > 0 && (
            <div className="card">
              <h2 className="text-sm font-semibold text-gray-300 mb-4 flex items-center gap-2">
                <XCircle className="w-4 h-4 text-accent-red" />
                Failed Tasks ({failedTasks.length})
              </h2>
              <div className="space-y-2">
                {failedTasks.map(task => (
                  <Link
                    key={task.id}
                    href={`/dashboard/tasks/${task.id}`}
                    className="flex items-center gap-3 p-3 rounded-md bg-background-elevated border border-red-500/20 hover:border-red-500/40 transition-all duration-150 group"
                  >
                    <StatusBadge status={task.status} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-gray-200 font-medium truncate group-hover:text-accent-red transition-colors">
                        {task.title}
                      </div>
                      <div className="text-xs font-mono text-gray-500 mt-0.5">
                        {formatDistanceToNow(new Date(task.updated_at), { addSuffix: true })} ·{' '}
                        {task.subtasks.filter(s => ['failed', 'dlq'].includes(s.status)).length} failed subtasks
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Failed/Retried Subtasks */}
          {failedSubtasks.length > 0 && (
            <div className="card">
              <h2 className="text-sm font-semibold text-gray-300 mb-4 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-accent-amber" />
                Failed / Retried Subtasks ({failedSubtasks.length})
              </h2>
              <div className="space-y-2">
                {failedSubtasks.map(st => (
                  <div
                    key={st.id}
                    className="p-3 rounded-md bg-background-elevated border border-border"
                  >
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <AgentBadge agentType={st.agent_type} />
                        <span className="text-sm text-gray-200 font-medium truncate">{st.name}</span>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <StatusBadge status={st.status} />
                        {st.retry_count > 0 && (
                          <span className="text-xs font-mono text-accent-amber bg-amber-900/20 border border-amber-700/30 px-1.5 py-0.5 rounded">
                            retry ×{st.retry_count}
                          </span>
                        )}
                      </div>
                    </div>
                    {st.error_message && (
                      <div className="flex items-start gap-1.5 text-xs font-mono text-accent-red bg-red-900/10 border border-red-700/20 rounded p-2">
                        <XCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                        <span>{st.error_message}</span>
                      </div>
                    )}
                    <div className="mt-2 text-xs text-gray-600 font-mono">
                      From:{' '}
                      <Link
                        href={`/dashboard/tasks/${(st as any).taskId}`}
                        className="text-accent-cyan hover:underline"
                      >
                        {(st as any).taskTitle}
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
