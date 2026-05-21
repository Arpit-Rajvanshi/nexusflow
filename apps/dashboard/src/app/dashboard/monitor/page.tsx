'use client'

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { MetricCard } from '@/components/ui/MetricCard'
import { Activity, Database, Wifi, Server, RefreshCw } from 'lucide-react'

export default function SystemMonitorPage() {
  const { data: health, isLoading: healthLoading, refetch } = useQuery({
    queryKey: ['system-health-detail'],
    queryFn: () => api.getSystemHealth(),
    refetchInterval: 10_000,
  })

  const { data: taskData } = useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.listTasks(100),
    refetchInterval: 10_000,
  })

  const tasks = taskData?.tasks || []
  const running = tasks.filter(t => ['running', 'planned', 'planning', 'queued'].includes(t.status))
  const completed = tasks.filter(t => t.status === 'completed')
  const failed = tasks.filter(t => ['failed', 'dlq'].includes(t.status))

  const statusColor = (s: string) =>
    s === 'healthy' ? 'text-accent-emerald' : 'text-accent-red'

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">System Monitor</h1>
          <p className="text-sm text-gray-500 mt-1 font-mono">Live infrastructure health</p>
        </div>
        <button onClick={() => refetch()} className="btn-ghost flex items-center gap-1.5 text-xs">
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Service health cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card">
          <div className="flex items-center gap-2 mb-2 text-gray-500">
            <Server className="w-3.5 h-3.5" />
            <span className="text-xs font-mono uppercase">Gateway</span>
          </div>
          <div className={`text-sm font-mono font-bold ${healthLoading ? 'text-gray-600' : statusColor(health?.gateway || '')}`}>
            {healthLoading ? 'Checking...' : health?.gateway === 'healthy' ? 'HEALTHY' : 'DEGRADED'}
          </div>
        </div>

        <div className="card">
          <div className="flex items-center gap-2 mb-2 text-gray-500">
            <Database className="w-3.5 h-3.5" />
            <span className="text-xs font-mono uppercase">PostgreSQL</span>
          </div>
          <div className={`text-sm font-mono font-bold ${statusColor(health?.database || '')}`}>
            {health?.database === 'healthy' ? 'HEALTHY' : health?.database || '–'}
          </div>
        </div>

        <div className="card">
          <div className="flex items-center gap-2 mb-2 text-gray-500">
            <Activity className="w-3.5 h-3.5" />
            <span className="text-xs font-mono uppercase">Redis</span>
          </div>
          <div className={`text-sm font-mono font-bold ${statusColor(health?.redis || '')}`}>
            {health?.redis === 'healthy' ? 'HEALTHY' : health?.redis || '–'}
          </div>
        </div>

        <div className="card">
          <div className="flex items-center gap-2 mb-2 text-gray-500">
            <Wifi className="w-3.5 h-3.5" />
            <span className="text-xs font-mono uppercase">Overall</span>
          </div>
          <div className={`text-sm font-mono font-bold ${statusColor(health?.overall || '')}`}>
            {health?.overall?.toUpperCase() || '–'}
          </div>
        </div>
      </div>

      {/* Task metrics */}
      <div className="grid grid-cols-3 gap-4">
        <MetricCard label="Active Tasks" value={running.length} icon={<Activity className="w-4 h-4"/>} color="cyan" />
        <MetricCard label="Completed (session)" value={completed.length} icon={<Activity className="w-4 h-4"/>} color="emerald" />
        <MetricCard label="Failed / DLQ" value={failed.length} icon={<Activity className="w-4 h-4"/>} color="red" />
      </div>

      {/* Health check response */}
      {health && (
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Raw Health Response</h2>
          <pre className="text-xs font-mono text-gray-400 bg-background p-4 rounded border border-border overflow-auto">
            {JSON.stringify(health, null, 2)}
          </pre>
        </div>
      )}

      <div className="card border-neon">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Observability Endpoints</h2>
        <div className="space-y-2 text-xs font-mono">
          {[
            { label: 'API Docs',         url: 'http://localhost:8000/api/docs' },
            { label: 'Health Check',     url: 'http://localhost:8000/health' },
            { label: 'System Health',    url: 'http://localhost:8000/api/v1/system/health' },
            { label: 'Metrics',          url: 'http://localhost:8000/api/v1/system/metrics' },
            { label: 'Streaming Health', url: 'http://localhost:8001/health' },
          ].map(({ label, url }) => (
            <div key={url} className="flex items-center justify-between p-2 rounded bg-background-elevated">
              <span className="text-gray-400">{label}</span>
              <a href={url} target="_blank" rel="noopener noreferrer" className="text-accent-cyan hover:underline">
                {url}
              </a>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
