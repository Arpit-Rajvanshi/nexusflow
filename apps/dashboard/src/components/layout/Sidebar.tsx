'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard, Send, History, Activity,
  AlertTriangle, Settings, Zap, ChevronRight
} from 'lucide-react'
import clsx from 'clsx'

const navItems = [
  { href: '/dashboard', label: 'Overview', icon: LayoutDashboard },
  { href: '/dashboard/submit', label: 'Submit Task', icon: Send },
  { href: '/dashboard/tasks', label: 'Task History', icon: History },
  { href: '/dashboard/monitor', label: 'System Monitor', icon: Activity },
  { href: '/dashboard/failures', label: 'Failure Inspector', icon: AlertTriangle },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="w-56 bg-background-surface border-r border-border flex flex-col flex-shrink-0">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-border">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-md bg-accent-cyan/10 border border-accent-cyan/30 flex items-center justify-center">
            <Zap className="w-4 h-4 text-accent-cyan" />
          </div>
          <div>
            <div className="text-sm font-bold text-gray-100 leading-none">NexusFlow</div>
            <div className="text-xs text-gray-500 font-mono mt-0.5">v1.0.0</div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-1">
        <div className="px-2 mb-3">
          <span className="text-xs font-medium text-gray-600 uppercase tracking-wider">Navigation</span>
        </div>
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = pathname === href
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-all duration-150 group',
                active
                  ? 'bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/20'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-background-elevated'
              )}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              <span className="font-medium">{label}</span>
              {active && (
                <ChevronRight className="w-3 h-3 ml-auto text-accent-cyan" />
              )}
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-border">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-accent-emerald animate-pulse-slow" />
          <span className="text-xs text-gray-500 font-mono">System Operational</span>
        </div>
      </div>
    </aside>
  )
}
