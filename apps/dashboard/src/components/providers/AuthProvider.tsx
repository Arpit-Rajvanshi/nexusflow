'use client'

import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { api } from '@/lib/api'

interface AuthState {
  token: string | null
  username: string | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null)
  const [username, setUsername] = useState<string | null>(null)

  useEffect(() => {
    // Hydrate from localStorage on mount
    const stored = localStorage.getItem('nexusflow_token')
    const storedUser = localStorage.getItem('nexusflow_user')
    if (stored) {
      setToken(stored)
      api.setToken(stored)
    }
    if (storedUser) setUsername(storedUser)
  }, [])

  const login = async (user: string, password: string) => {
    const { access_token } = await api.getToken(user, password)
    setToken(access_token)
    setUsername(user)
    api.setToken(access_token)
    localStorage.setItem('nexusflow_token', access_token)
    localStorage.setItem('nexusflow_user', user)
  }

  const logout = () => {
    setToken(null)
    setUsername(null)
    api.setToken(null)
    localStorage.removeItem('nexusflow_token')
    localStorage.removeItem('nexusflow_user')
  }

  return (
    <AuthContext.Provider
      value={{ token, username, isAuthenticated: !!token, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
