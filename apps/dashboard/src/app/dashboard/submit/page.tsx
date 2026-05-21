'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { Send, Loader2, ChevronDown, ChevronUp, Info } from 'lucide-react'

const EXAMPLE_TASKS = [
  {
    title: 'AI Chip Startup Analysis',
    description: 'Research leading AI chip startups (NVIDIA, AMD, Cerebras, Groq, Tenstorrent), compare their latest funding rounds, analyze competitive positioning and market trends, and generate a comprehensive investor report with recommendations.',
    priority: 8,
  },
  {
    title: 'LLM Benchmark Comparison Report',
    description: 'Compare GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro, and Llama 3.1 across reasoning, coding, math, and instruction-following benchmarks. Summarize trade-offs and recommend models for different use cases.',
    priority: 5,
  },
  {
    title: 'Remote Work Policy Analysis',
    description: 'Research current enterprise remote work policies across Fortune 500 companies, analyze productivity data and employee sentiment, identify emerging trends, and produce a policy recommendation document for a 200-person tech company.',
    priority: 3,
  },
]

export default function SubmitTaskPage() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState(5)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [showExamples, setShowExamples] = useState(false)
  const router = useRouter()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !description.trim()) return
    setError('')
    setSubmitting(true)
    try {
      const result = await api.submitTask({ title, description, priority })
      router.push(`/dashboard/tasks/${result.task_id}`)
    } catch (err: any) {
      setError(err.message || 'Task submission failed')
      setSubmitting(false)
    }
  }

  const fillExample = (ex: typeof EXAMPLE_TASKS[0]) => {
    setTitle(ex.title)
    setDescription(ex.description)
    setPriority(ex.priority)
    setShowExamples(false)
  }

  const priorityLabel = (p: number) => {
    if (p >= 8) return { label: 'Critical', color: 'text-accent-red' }
    if (p >= 5) return { label: 'Normal', color: 'text-accent-cyan' }
    return { label: 'Low', color: 'text-gray-400' }
  }

  const { label: prioLabel, color: prioColor } = priorityLabel(priority)

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="text-xl font-bold text-gray-100">Submit Task</h1>
        <p className="text-sm text-gray-500 mt-1 font-mono">
          Complex multi-step tasks are decomposed and executed by specialized agents
        </p>
      </div>

      {/* Pipeline info */}
      <div className="card border border-accent-cyan/20 bg-accent-cyan/5">
        <div className="flex items-start gap-3">
          <Info className="w-4 h-4 text-accent-cyan flex-shrink-0 mt-0.5" />
          <div className="text-xs text-gray-400 font-mono space-y-1">
            <p>Tasks are automatically decomposed into subtasks by the Planner Agent.</p>
            <p>Execution pipeline: <span className="text-accent-cyan">Retriever → Analyzer → Writer → Validator</span></p>
            <p>You'll be redirected to the live execution view after submission.</p>
          </div>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1.5">
            Task Title <span className="text-accent-red">*</span>
          </label>
          <input
            type="text"
            value={title}
            onChange={e => setTitle(e.target.value)}
            className="input-field w-full"
            placeholder="e.g. AI Chip Startup Analysis"
            maxLength={200}
            required
          />
          <div className="text-xs text-gray-600 mt-1 text-right font-mono">{title.length}/200</div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1.5">
            Task Description <span className="text-accent-red">*</span>
          </label>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            className="input-field w-full resize-none"
            placeholder="Describe the task in detail. The more context you provide, the better the agents can decompose and execute it."
            rows={6}
            required
          />
          <div className="text-xs text-gray-600 mt-1 font-mono">
            {description.length} chars · Aim for 100-500 chars for best results
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1.5">
            Priority: <span className={`font-mono ${prioColor}`}>{prioLabel} ({priority})</span>
          </label>
          <input
            type="range"
            min={1}
            max={10}
            value={priority}
            onChange={e => setPriority(Number(e.target.value))}
            className="w-full accent-accent-cyan"
          />
          <div className="flex justify-between text-xs text-gray-600 font-mono mt-1">
            <span>1 — Low</span>
            <span>5 — Normal</span>
            <span>10 — Critical</span>
          </div>
        </div>

        {error && (
          <div className="text-accent-red text-sm p-3 rounded bg-red-500/10 border border-red-500/20 font-mono">
            Error: {error}
          </div>
        )}

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={submitting || !title || !description}
            className="btn-primary flex items-center gap-2 px-6"
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Submitting...
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                Submit Task
              </>
            )}
          </button>

          <button
            type="button"
            onClick={() => setShowExamples(!showExamples)}
            className="btn-ghost flex items-center gap-1.5"
          >
            Examples
            {showExamples ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>
      </form>

      {/* Example tasks */}
      {showExamples && (
        <div className="card space-y-3 animate-slide-in">
          <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider font-mono">
            Example Tasks
          </h3>
          {EXAMPLE_TASKS.map((ex, i) => (
            <button
              key={i}
              onClick={() => fillExample(ex)}
              className="w-full text-left p-3 rounded-md bg-background-elevated border border-border hover:border-accent-cyan/30 transition-all duration-150 group"
            >
              <div className="text-sm font-medium text-gray-200 group-hover:text-accent-cyan transition-colors">
                {ex.title}
              </div>
              <div className="text-xs text-gray-500 mt-1 line-clamp-2 font-mono">
                {ex.description}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
