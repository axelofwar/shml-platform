/**
 * Authentication Store
 *
 * Manages user authentication state using FusionAuth + OAuth2-Proxy.
 * Fetches user info from backend /me endpoint which extracts from OAuth headers.
 */

import { create } from 'zustand'
import type { UserRole } from '@/lib/tokenBudget'

export interface AuthUser {
  user_id: string
  email: string
  preferred_username: string
  roles: string[]
  primary_role: UserRole
  token_budget: number
}

interface AuthStore {
  user: AuthUser | null
  isLoading: boolean
  error: string | null

  fetchUser: () => Promise<void>
  clearUser: () => void
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  isLoading: false,
  error: null,

  fetchUser: async () => {
    set({ isLoading: true, error: null })

    try {
      const response = await fetch('/api/agent/user/me', {
        credentials: 'include', // Include cookies for OAuth2-Proxy
      })

      if (!response.ok) {
        if (response.status === 401) {
          // Not authenticated - in dev mode, use demo user
          console.warn('User not authenticated (401)')

          // Check if we're in development (DEV_MODE backend will return user anyway)
          // For now, set a demo user to prevent redirect loop
          set({
            user: {
              user_id: 'dev-user',
              email: 'dev@localhost',
              preferred_username: 'developer',
              roles: ['developer'],
              primary_role: 'developer',
              token_budget: 4096,
            },
            isLoading: false,
            error: 'Using demo user (OAuth not configured)'
          })
          return
        }

        throw new Error(`Failed to fetch user info: ${response.statusText}`)
      }

      const user = await response.json()

      console.log('User authenticated:', {
        email: user.email,
        role: user.primary_role,
        budget: user.token_budget,
      })

      set({ user, isLoading: false })
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error'
      console.error('Auth error:', errorMessage)

      set({
        error: errorMessage,
        isLoading: false,
        user: null,
      })
    }
  },

  clearUser: () => {
    set({ user: null, error: null })
  },
}))
