'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { api, ExecutionEvent, TaskStatus } from '@/lib/api'

const TERMINAL_STATUSES: TaskStatus[] = ['completed', 'failed', 'cancelled', 'dlq']

export function useTaskStream(
  taskId: string,
  currentStatus: TaskStatus | undefined,
  maxEvents = 500,
) {
  const [events, setEvents] = useState<ExecutionEvent[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttempts = useRef(0)
  const reconnectTimer = useRef<NodeJS.Timeout | undefined>(undefined)

  const isTerminal = currentStatus && TERMINAL_STATUSES.includes(currentStatus)

  const connect = useCallback(() => {
    if (isTerminal) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const url = api.getStreamingUrl(taskId)
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
      reconnectAttempts.current = 0
    }

    ws.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data) as ExecutionEvent
        if (event.type === 'ping' || event.type === 'connection.established') return

        setEvents(prev => {
          const next = [...prev, event]
          return next.length > maxEvents ? next.slice(-maxEvents) : next
        })

        if (
          event.event_type &&
          ['task.completed', 'task.failed', 'task.cancelled'].includes(event.event_type)
        ) {
          ws.close(1000, 'Task terminal')
        }
      } catch {
        // Non-JSON message ignored
      }
    }

    ws.onerror = () => {
      setIsConnected(false)
    }

    ws.onclose = (ev) => {
      setIsConnected(false)
      wsRef.current = null

      if (ev.code === 1000 || isTerminal) return

      const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 30_000)
      reconnectAttempts.current += 1
      reconnectTimer.current = setTimeout(connect, delay)
    }
  }, [taskId, isTerminal, maxEvents])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted')
        wsRef.current = null
      }
    }
  }, [connect])

  return { events, isConnected }
}
