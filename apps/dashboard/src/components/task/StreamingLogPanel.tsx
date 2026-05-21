'use client'

import { useEffect, useRef } from 'react'
import { ExecutionEvent } from '@/lib/api'
import { format } from 'date-fns'
import clsx from 'clsx'

const EVENT_COLORS: Record<string, string> = {
  'task.started': 'text-accent-cyan',
  'task.completed': 'text-accent-emerald',
  'task.failed': 'text-accent-red',
  'subtask.queued': 'text-gray-400',
  'subtask.started': 'text-accent-cyan',
  'subtask.completed': 'text-accent-emerald',
  'subtask.failed': 'text-accent-red',
  'subtask.retrying': 'text-accent-amber',
  'subtask.dlq': 'text-red-600',
  'agent.log': 'text-gray-300',
  'agent.partial_output': 'text-gray-400',
  'system.error': 'text-accent-red',
}

const EVENT_PREFIXES: Record<string, string> = {
  'task.started': '[TASK]',
  'task.completed': '[DONE]',
  'task.failed': '[FAIL]',
  'subtask.queued': '[QUEUE]',
  'subtask.started': '[RUN]',
  'subtask.completed': '[OK]',
  'subtask.failed': '[ERR]',
  'subtask.retrying': '[RETRY]',
  'subtask.dlq': '[DLQ]',
  'agent.log': '[LOG]',
  'agent.partial_output': '[OUT]',
  'system.error': '[SYS]',
}

interface Props {
  events: ExecutionEvent[]
}

export function StreamingLogPanel({ events }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new events
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length])

  const formatEventLine = (e: ExecutionEvent): string => {
    const prefix = EVENT_PREFIXES[e.event_type] || '[EVT]'
    const agentTag = e.agent_type ? ` [${e.agent_type.toUpperCase()}]` : ''
    const payload = e.payload

    if (e.event_type === 'agent.log') {
      return `${prefix}${agentTag} ${payload.message || ''}`
    }
    if (e.event_type === 'agent.partial_output') {
      return `${prefix}${agentTag} ${String(payload.text || '').slice(0, 120)}`
    }
    if (e.event_type === 'subtask.retrying') {
      return `${prefix}${agentTag} Retry attempt ${payload.retry_count} in ${Number(payload.delay || 0).toFixed(1)}s`
    }
    if (e.event_type === 'task.completed') {
      return `${prefix} Task complete — ${payload.total_tokens || 0} tokens, $${Number(payload.total_cost_usd || 0).toFixed(6)}`
    }
    if (payload.message) return `${prefix}${agentTag} ${payload.message}`
    if (payload.reason) return `${prefix}${agentTag} ${payload.reason}`
    return `${prefix}${agentTag} ${JSON.stringify(payload).slice(0, 100)}`
  }

  return (
    <div className="flex-1 overflow-auto bg-background rounded-md border border-border p-3 font-mono text-xs">
      {events.length === 0 ? (
        <div className="text-gray-600 italic">Waiting for execution events...</div>
      ) : (
        <>
          {events.map((event, idx) => (
            <div
              key={`${event.id}-${idx}`}
              className={clsx(
                'leading-6 hover:bg-background-elevated px-1 rounded transition-colors',
                event.is_partial && 'opacity-75',
                EVENT_COLORS[event.event_type] || 'text-gray-400'
              )}
            >
              <span className="text-gray-600 select-none mr-2">
                {format(new Date(event.timestamp), 'HH:mm:ss.SSS')}
              </span>
              {formatEventLine(event)}
            </div>
          ))}
          <div ref={bottomRef} />
        </>
      )}
    </div>
  )
}
