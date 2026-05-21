'use client'

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { formatDistanceToNow } from 'date-fns'
import Link from 'next/link'
import { ArrowRight, Search, Filter } from 'lucide-react'
import { useState } from 'react'

export default function TaskHistoryPage() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.listTasks(50),
    refetchInterval: 15_000,
  })

  const tasks = data?.tasks || []
  const filtered = tasks.filter(t => {
    const matchesSearch = t.title.toLowerCase().includes(search.toLowerCase())
    const matchesStatus = statusFilter === 'all' || t.status === statusFilter
    return matchesSearch && matchesStatus
  })

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Task History</h1>
          <p className="text-sm text-gray-500 mt-1 font-mono">
            {tasks.length} tasks total
          </p>
        </div>
        <button onClick={() => refetch()} className="btn-ghost text-xs">Refresh</button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search tasks..."
            className="input-field w-full pl-9"
          />
        </div>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="input-field"
        >
          <option value="all">All statuses</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="pending">Pending</option>
          <option value="dlq">DLQ</option>
        </select>
      </div>

      {/* Task table */}
      <div className="card">
        {isLoading ? (
          <div className="space-y-3">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-16 bg-background-elevated rounded animate-pulse" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 text-gray-600 font-mono text-sm">
            No tasks match your filters.{' '}
            <Link href="/dashboard/submit" className="text-accent-cyan hover:underline">
              Submit a task →
            </Link>
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map(task => (
              <Link
                key={task.id}
                href={`/dashboard/tasks/${task.id}`}
                className="flex items-center gap-4 p-3 rounded-md bg-background-elevated border border-border hover:border-accent-cyan/30 transition-all duration-150 group"
              >
                <StatusBadge status={task.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-gray-200 font-medium truncate group-hover:text-accent-cyan transition-colors">
                    {task.title}
                  </div>
                  <div className="text-xs text-gray-500 font-mono mt-0.5 flex items-center gap-3">
                    <span>{task.subtask_count} subtasks</span>
                    <span>{task.total_tokens_used.toLocaleString()} tokens</span>
                    <span>${task.total_cost_usd.toFixed(6)}</span>
                  </div>
                </div>
                <div className="text-xs text-gray-600 font-mono flex-shrink-0 hidden sm:block">
                  {formatDistanceToNow(new Date(task.created_at), { addSuffix: true })}
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
