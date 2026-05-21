'use client'

import { ReactNode } from 'react'
import clsx from 'clsx'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

const COLORS = {
  cyan:    'text-accent-cyan border-accent-cyan/20 bg-accent-cyan/5',
  purple:  'text-accent-purple border-accent-purple/20 bg-accent-purple/5',
  emerald: 'text-accent-emerald border-accent-emerald/20 bg-accent-emerald/5',
  red:     'text-accent-red border-accent-red/20 bg-accent-red/5',
  amber:   'text-accent-amber border-accent-amber/20 bg-accent-amber/5',
}

interface Props {
  label: string
  value: number | string
  icon: ReactNode
  color?: keyof typeof COLORS
  trend?: 'up' | 'down' | 'flat'
}

export function MetricCard({ label, value, icon, color = 'cyan', trend }: Props) {
  return (
    <div className={clsx('card border', COLORS[color])}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-mono text-gray-500 uppercase tracking-wider">{label}</span>
        <span className="opacity-60">{icon}</span>
      </div>
      <div className="flex items-end justify-between">
        <div className="metric-value text-xl">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </div>
        {trend && (
          <div className={clsx(
            'text-xs flex items-center gap-0.5',
            trend === 'up' ? 'text-accent-emerald' : trend === 'down' ? 'text-accent-red' : 'text-gray-500'
          )}>
            {trend === 'up' ? <TrendingUp className="w-3 h-3" /> :
             trend === 'down' ? <TrendingDown className="w-3 h-3" /> :
             <Minus className="w-3 h-3" />}
          </div>
        )}
      </div>
    </div>
  )
}
