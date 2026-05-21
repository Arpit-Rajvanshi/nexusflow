import type { Metadata } from 'next'
import '../styles/globals.css'
import { QueryProvider } from '@/components/providers/QueryProvider'
import { AuthProvider } from '@/components/providers/AuthProvider'

export const metadata: Metadata = {
  title: 'NexusFlow — Agentic AI Orchestration',
  description:
    'Production-grade multi-agent AI orchestration platform with real-time DAG execution, streaming, and observability.',
  keywords: ['AI', 'orchestration', 'multi-agent', 'workflow', 'distributed systems'],
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body>
        <QueryProvider>
          <AuthProvider>
            {children}
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  )
}
