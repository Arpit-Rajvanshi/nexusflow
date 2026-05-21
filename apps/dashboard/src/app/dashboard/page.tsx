'use client'

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { MetricCard } from '@/components/ui/MetricCard'
import { formatDistanceToNow } from 'date-fns'
import Link from 'next/link'
import {
  Activity, CheckCircle2, XCircle, Clock,
  Zap, Database, ArrowRight, TrendingUp
} from 'lucide-react'

export default function DashboardOverview() {
  const { data, isLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.listTasks(20),
    refetchInterval: 10_000,
  })

  const tasks = data?.tasks || []

  const stats = {
    total: tasks.length,
    running: tasks.filter(t => ['running', 'planning', 'planned', 'queued'].includes(t.status)).length,
    completed: tasks.filter(t => t.status === 'completed').length,
    failed: tasks.filter(t => ['failed', 'dlq'].includes(t.status)).length,
    totalTokens: tasks.reduce((s, t) => s + t.total_tokens_used, 0),
    totalCost: tasks.reduce((s, t) => s + t.total_cost_usd, 0),
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-bold text-gray-100">System Overview</h1>
        <p className="text-sm text-gray-500 mt-1 font-mono">
          Real-time orchestration metrics · Auto-refreshing every 10s
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Active Tasks"
          value={stats.running}
          icon={<Activity className="w-4 h-4" />}
          color="cyan"
          trend={stats.running > 0 ? 'up' : 'flat'}
        />
        <MetricCard
          label="Completed"
          value={stats.completed}
          icon={<CheckCircle2 className="w-4 h-4" />}
          color="emerald"
        />
        <MetricCard
          label="Failed"
          value={stats.failed}
          icon={<XCircle className="w-4 h-4" />}
          color="red"
        />
        <MetricCard
          label="Total Cost"
          value={`$${stats.totalCost.toFixed(4)}`}
          icon={<TrendingUp className="w-4 h-4" />}
          color="purple"
        />
      </div>

      {/* Secondary metrics */}
      <div className="grid grid-cols-2 gap-4">
        <div className="card">
          <div className="flex items-center gap-2 text-gray-500 mb-2">
            <Database className="w-3.5 h-3.5" />
            <span className="text-xs font-mono uppercase tracking-wider">Total Tokens</span>
          </div>
          <div className="metric-value text-accent-cyan">
            {stats.totalTokens.toLocaleString()}
          </div>
          <div className="text-xs text-gray-600 mt-1 font-mono">across {stats.total} tasks</div>
        </div>
        <div className="card">
          <div className="flex items-center gap-2 text-gray-500 mb-2">
            <Zap className="w-3.5 h-3.5" />
            <span className="text-xs font-mono uppercase tracking-wider">Avg Cost/Task</span>
          </div>
          <div className="metric-value text-accent-purple">
            ${stats.total > 0 ? (stats.totalCost / stats.total).toFixed(4) : '0.0000'}
          </div>
          <div className="text-xs text-gray-600 mt-1 font-mono">gpt-4o pricing</div>
        </div>
      </div>

      {/* Recent tasks */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-300">Recent Tasks</h2>
          <Link
            href="/dashboard/tasks"
            className="flex items-center gap-1 text-xs text-accent-cyan hover:text-cyan-400 transition-colors font-mono"
          >
            View all <ArrowRight className="w-3 h-3" />
          </Link>
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-12 bg-background-elevated rounded animate-pulse" />
            ))}
          </div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-8 text-gray-600 font-mono text-sm">
            No tasks yet. <Link href="/dashboard/submit" className="text-accent-cyan hover:underline">Submit your first task →</Link>
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.slice(0, 8).map(task => (
              <Link
                key={task.id}
                href={`/dashboard/tasks/${task.id}`}
                className="flex items-center gap-3 p-3 rounded-md bg-background-elevated border border-border hover:border-accent-cyan/30 transition-all duration-150 group"
              >
                <StatusBadge status={task.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-gray-200 font-medium truncate group-hover:text-accent-cyan transition-colors">
                    {task.title}
                  </div>
                  <div className="text-xs text-gray-500 font-mono mt-0.5">
                    {task.subtask_count} subtasks · {task.total_tokens_used.toLocaleString()} tokens ·{' '}
                    {formatDistanceToNow(new Date(task.created_at), { addSuffix: true })}
                  </div>
                </div>
                <ArrowRight className="w-3.5 h-3.5 text-gray-600 group-hover:text-accent-cyan transition-colors flex-shrink-0" />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
