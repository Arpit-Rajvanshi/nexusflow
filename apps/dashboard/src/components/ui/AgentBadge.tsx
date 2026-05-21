'use client'

import clsx from 'clsx'

const AGENT_CONFIG = {
  retriever:    { label: 'Retriever',    color: 'text-sky-400',    bg: 'bg-sky-900/30 border-sky-700/40' },
  analyzer:     { label: 'Analyzer',     color: 'text-purple-400', bg: 'bg-purple-900/30 border-purple-700/40' },
  writer:       { label: 'Writer',       color: 'text-emerald-400',bg: 'bg-emerald-900/30 border-emerald-700/40' },
  validator:    { label: 'Validator',    color: 'text-amber-400',  bg: 'bg-amber-900/30 border-amber-700/40' },
  planner:      { label: 'Planner',      color: 'text-orange-400', bg: 'bg-orange-900/30 border-orange-700/40' },
}

interface Props {
  agentType: string
  size?: 'sm' | 'md'
}

export function AgentBadge({ agentType, size = 'md' }: Props) {
  const config = AGENT_CONFIG[agentType as keyof typeof AGENT_CONFIG] || {
    label: agentType,
    color: 'text-gray-400',
    bg: 'bg-background-elevated border-border',
  }

  return (
    <span
      className={clsx(
        'agent-badge border font-mono',
        config.color, config.bg,
        size === 'sm' ? 'text-[10px] px-1.5 py-0.5' : 'text-xs px-2 py-0.5'
      )}
    >
      {config.label}
    </span>
  )
}
