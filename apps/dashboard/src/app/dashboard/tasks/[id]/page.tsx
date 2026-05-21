'use client'

import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useTaskStream } from '@/hooks/useTaskStream'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { AgentBadge } from '@/components/ui/AgentBadge'
import { StreamingLogPanel } from '@/components/task/StreamingLogPanel'
import { DAGVisualization } from '@/components/task/DAGVisualization'
import { formatDistanceToNow, format } from 'date-fns'
import { Clock, Coins, Zap, RefreshCw, XCircle } from 'lucide-react'

export default function TaskDetailPage() {
  const params = useParams()
  const id = typeof params?.id === 'string' ? params.id : ''

  const { data: task, refetch } = useQuery({
    queryKey: ['task', id],
    queryFn: () => api.getTask(id),
    refetchInterval: (query) =>
      // Stop polling once terminal
      ['completed', 'failed', 'cancelled', 'dlq'].includes((query?.state?.data as any)?.status || '')
        ? false
        : 5000,
  })

  const { events, isConnected } = useTaskStream(id, task?.status)

  if (!task) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-accent-cyan/30 border-t-accent-cyan rounded-full animate-spin" />
      </div>
    )
  }

  const duration = task.completed_at
    ? `${((new Date(task.completed_at).getTime() - new Date(task.created_at).getTime()) / 1000).toFixed(1)}s`
    : null

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Task header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <StatusBadge status={task.status} large />
            {isConnected && (
              <div className="flex items-center gap-1.5 text-xs font-mono text-accent-emerald">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-emerald animate-pulse" />
                Live
              </div>
            )}
          </div>
          <h1 className="text-lg font-bold text-gray-100">{task.title}</h1>
          <p className="text-sm text-gray-500 mt-1 max-w-2xl">{task.description}</p>
        </div>
        <button onClick={() => refetch()} className="btn-ghost flex items-center gap-1.5 flex-shrink-0">
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { icon: Clock, label: 'Created', value: formatDistanceToNow(new Date(task.created_at), { addSuffix: true }) },
          { icon: Zap, label: 'Tokens', value: task.total_tokens_used.toLocaleString() },
          { icon: Coins, label: 'Cost', value: `$${task.total_cost_usd.toFixed(6)}` },
          { icon: Clock, label: duration ? 'Duration' : 'Running for', value: duration || formatDistanceToNow(new Date(task.created_at)) },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="card-elevated flex items-center gap-3">
            <Icon className="w-4 h-4 text-gray-500 flex-shrink-0" />
            <div>
              <div className="text-xs text-gray-500">{label}</div>
              <div className="text-sm font-mono font-medium text-gray-200">{value}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Main content */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* DAG Visualization */}
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Execution DAG</h2>
          <DAGVisualization subtasks={task.subtasks} />
        </div>

        {/* Live streaming logs */}
        <div className="card flex flex-col" style={{ height: '400px' }}>
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Execution Log</h2>
          <StreamingLogPanel events={events} />
        </div>
      </div>

      {/* Subtask details */}
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">
          Subtasks ({task.subtasks.length})
        </h2>
        <div className="space-y-2">
          {task.subtasks.map(st => (
            <div
              key={st.id}
              className="p-3 rounded-md bg-background-elevated border border-border"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                  <AgentBadge agentType={st.agent_type} />
                  <span className="text-sm text-gray-200 font-medium truncate">{st.name}</span>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <StatusBadge status={st.status} />
                  {st.retry_count > 0 && (
                    <span className="text-xs font-mono text-accent-amber">
                      retry ×{st.retry_count}
                    </span>
                  )}
                </div>
              </div>
              {st.error_message && (
                <div className="mt-2 flex items-start gap-1.5 text-xs text-accent-red font-mono">
                  <XCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                  <span className="line-clamp-2">{st.error_message}</span>
                </div>
              )}
              <div className="flex gap-4 mt-2 text-xs font-mono text-gray-600">
                {st.tokens_used > 0 && <span>{st.tokens_used.toLocaleString()} tokens</span>}
                {st.started_at && st.completed_at && (
                  <span>
                    {((new Date(st.completed_at).getTime() - new Date(st.started_at).getTime()) / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
