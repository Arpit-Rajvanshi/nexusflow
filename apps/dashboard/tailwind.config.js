/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // NexusFlow design system — calibrated for engineering dashboards
        background: {
          DEFAULT: '#0a0c10',
          surface: '#0f1117',
          elevated: '#161b22',
          overlay: '#1c2128',
        },
        border: {
          DEFAULT: '#21262d',
          subtle: '#161b22',
          emphasis: '#3d444d',
        },
        accent: {
          cyan: '#00d4ff',
          'cyan-dim': '#0ea5e9',
          purple: '#a855f7',
          emerald: '#10b981',
          amber: '#f59e0b',
          red: '#ef4444',
        },
        status: {
          pending: '#6b7280',
          queued: '#3b82f6',
          running: '#f59e0b',
          completed: '#10b981',
          failed: '#ef4444',
          retrying: '#f97316',
          dlq: '#dc2626',
          cancelled: '#6b7280',
        },
        agent: {
          retriever: '#0ea5e9',
          analyzer: '#a855f7',
          writer: '#10b981',
          validator: '#f59e0b',
          planner: '#f97316',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-in': 'slideIn 0.2s ease-out',
        'fade-in': 'fadeIn 0.3s ease-out',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        slideIn: {
          '0%': { transform: 'translateY(4px)', opacity: 0 },
          '100%': { transform: 'translateY(0)', opacity: 1 },
        },
        fadeIn: {
          '0%': { opacity: 0 },
          '100%': { opacity: 1 },
        },
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(0, 212, 255, 0.2)' },
          '100%': { boxShadow: '0 0 20px rgba(0, 212, 255, 0.5)' },
        },
      },
      backgroundImage: {
        'grid-pattern': "linear-gradient(rgba(0,212,255,0.03) 1px, transparent 1px), linear-gradient(to right, rgba(0,212,255,0.03) 1px, transparent 1px)",
      },
      backgroundSize: {
        'grid': '40px 40px',
      },
    },
  },
  plugins: [],
}
