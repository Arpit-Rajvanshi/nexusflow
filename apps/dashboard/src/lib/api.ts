/**
 * NexusFlow API client.
 * Wraps fetch with auth token injection, base URL config, and error normalization.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8001'

class ApiClient {
  private token: string | null = null

  setToken(token: string | null) {
    this.token = token
  }

  private get headers(): Record<string, string> {
    const h: Record<string, string> = { 'Content-Type': 'application/json' }
    if (this.token) h['Authorization'] = `Bearer ${this.token}`
    return h
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: { ...this.headers, ...(options.headers as Record<string, string> || {}) },
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res.json()
  }

  async getToken(username: string, password: string) {
    return this.request<{ access_token: string; token_type: string }>('/auth/token', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
  }

  async submitTask(payload: {
    title: string
    description: string
    priority?: number
    metadata?: Record<string, unknown>
  }) {
    return this.request<{
      task_id: string
      status: string
      message: string
      streaming_url: string
    }>('/api/v1/tasks', { method: 'POST', body: JSON.stringify(payload) })
  }

  async listTasks(limit = 20, offset = 0) {
    return this.request<{ tasks: Task[]; total: number }>(`/api/v1/tasks?limit=${limit}&offset=${offset}`)
  }

  async getTask(taskId: string) {
    return this.request<Task>(`/api/v1/tasks/${taskId}`)
  }

  async getTaskEvents(taskId: string, limit = 200) {
    return this.request<{ events: ExecutionEvent[]; count: number }>(
      `/api/v1/tasks/${taskId}/events?limit=${limit}`
    )
  }

  async cancelTask(taskId: string) {
    return this.request<{ task_id: string; status: string }>(
      `/api/v1/tasks/${taskId}`,
      { method: 'DELETE' }
    )
  }

  async getSystemHealth() {
    return this.request<Record<string, string>>('/api/v1/system/health')
  }

  /** WebSocket URL for live task streaming */
  getStreamingUrl(taskId: string): string {
    return `${WS_URL}/ws/tasks/${taskId}?token=${this.token || ''}`
  }
}

export const api = new ApiClient()

// ─── Types ────────────────────────────────────────────────────────────────────

export interface Subtask {
  id: string
  name: string
  description: string
  agent_type: 'retriever' | 'analyzer' | 'writer' | 'validator' | 'planner'
  status: TaskStatus
  retry_count: number
  tokens_used: number
  cost_usd: number
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  depends_on?: string[]
}

export interface Task {
  id: string
  title: string
  description: string
  status: TaskStatus
  priority: number
  created_at: string
  updated_at: string
  completed_at: string | null
  subtask_count: number
  total_tokens_used: number
  total_cost_usd: number
  subtasks: Subtask[]
}

export interface ExecutionEvent {
  id: string
  event_type: string
  task_id: string
  subtask_id?: string
  agent_type?: string
  worker_id?: string
  payload: Record<string, unknown>
  is_partial: boolean
  sequence_number: number
  timestamp: string
  type?: string
}

export type TaskStatus =
  | 'pending' | 'planning' | 'planned' | 'queued'
  | 'running' | 'retrying' | 'completed' | 'failed'
  | 'cancelled' | 'dlq'
