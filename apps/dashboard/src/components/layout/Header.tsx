'use client'

import { useAuth } from '@/components/providers/AuthProvider'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { LogOut, User, Wifi, WifiOff, RefreshCw } from 'lucide-react'
import { useRouter } from 'next/navigation'

export function Header() {
  const { username, logout } = useAuth()
  const router = useRouter()

  const { data: health, isError } = useQuery({
    queryKey: ['system-health'],
    queryFn: () => api.getSystemHealth(),
    refetchInterval: 30_000,
  })

  const handleLogout = () => {
    logout()
    router.push('/')
  }

  const isHealthy = !isError && health?.overall === 'healthy'

  return (
    <header className="h-14 border-b border-border bg-background-surface px-6 flex items-center justify-between flex-shrink-0">
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-semibold text-gray-300">Orchestration Dashboard</h2>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-1.5">
          {isHealthy ? (
            <Wifi className="w-3.5 h-3.5 text-accent-emerald" />
          ) : (
            <WifiOff className="w-3.5 h-3.5 text-accent-red animate-pulse" />
          )}
          <span className={`text-xs font-mono ${isHealthy ? 'text-accent-emerald' : 'text-accent-red'}`}>
            {isHealthy ? 'All Systems Healthy' : 'Service Degraded'}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {health && (
          <div className="hidden md:flex items-center gap-4 text-xs font-mono text-gray-500">
            <span>
              Redis:{' '}
              <span className={health.redis === 'healthy' ? 'text-accent-emerald' : 'text-accent-red'}>
                {health.redis === 'healthy' ? '●' : '●'}
              </span>
            </span>
            <span>
              DB:{' '}
              <span className={health.database === 'healthy' ? 'text-accent-emerald' : 'text-accent-red'}>
                {health.database === 'healthy' ? '●' : '●'}
              </span>
            </span>
          </div>
        )}

        <div className="flex items-center gap-2 text-sm text-gray-400">
          <User className="w-3.5 h-3.5" />
          <span className="font-mono text-xs">{username}</span>
        </div>

        <button
          onClick={handleLogout}
          className="btn-ghost flex items-center gap-1.5 text-xs"
          title="Sign out"
        >
          <LogOut className="w-3.5 h-3.5" />
          Sign out
        </button>
      </div>
    </header>
  )
}
