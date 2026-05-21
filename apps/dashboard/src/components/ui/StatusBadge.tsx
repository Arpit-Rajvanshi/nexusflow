'use client'

import clsx from 'clsx'
import { TaskStatus } from '@/lib/api'

const STATUS_CONFIG: Record<TaskStatus, { label: string; dot: string; text: string }> = {
  pending:   { label: 'Pending',   dot: 'bg-gray-500',        text: 'text-gray-400' },
  planning:  { label: 'Planning',  dot: 'bg-blue-400 animate-pulse', text: 'text-blue-400' },
  planned:   { label: 'Planned',   dot: 'bg-blue-500',        text: 'text-blue-400' },
  queued:    { label: 'Queued',    dot: 'bg-blue-500',        text: 'text-blue-400' },
  running:   { label: 'Running',   dot: 'bg-amber-400 animate-pulse', text: 'text-amber-400' },
  retrying:  { label: 'Retrying',  dot: 'bg-orange-400 animate-pulse', text: 'text-orange-400' },
  completed: { label: 'Completed', dot: 'bg-emerald-500',     text: 'text-emerald-400' },
  failed:    { label: 'Failed',    dot: 'bg-red-500',         text: 'text-red-400' },
  cancelled: { label: 'Cancelled', dot: 'bg-gray-600',        text: 'text-gray-500' },
  dlq:       { label: 'DLQ',      dot: 'bg-red-700',         text: 'text-red-600' },
}

interface Props {
  status: TaskStatus
  large?: boolean
}

export function StatusBadge({ status, large }: Props) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.pending

  return (
    <span
      className={clsx(
        'status-badge',
        large ? 'text-sm px-2.5 py-1' : '',
        'bg-background-elevated border border-border',
        config.text
      )}
    >
      <span className={clsx('w-1.5 h-1.5 rounded-full flex-shrink-0', config.dot)} />
      {config.label}
    </span>
  )
}
