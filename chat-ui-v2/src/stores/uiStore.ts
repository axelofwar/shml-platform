/**
 * UI Store - Manages interface state (sidebar, modals, theme, etc.)
 *
 * Persists UI preferences to localStorage
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// UI state
interface UIState {
  // Sidebar
  isSidebarOpen: boolean
  sidebarWidth: number

  // Workflow panel
  isWorkflowPanelOpen: boolean
  workflowPanelHeight: number

  // Command palette
  isCommandPaletteOpen: boolean

  // Modals
  activeModal: string | null

  // Theme
  theme: 'light' | 'dark' | 'system'

  // Metrics dashboard
  isMetricsDashboardOpen: boolean

  // Actions
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
  setSidebarWidth: (width: number) => void

  toggleWorkflowPanel: () => void
  setWorkflowPanelOpen: (open: boolean) => void
  setWorkflowPanelHeight: (height: number) => void

  toggleCommandPalette: () => void
  setCommandPaletteOpen: (open: boolean) => void

  openModal: (modalId: string) => void
  closeModal: () => void

  setTheme: (theme: 'light' | 'dark' | 'system') => void

  toggleMetricsDashboard: () => void
  setMetricsDashboardOpen: (open: boolean) => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      // Initial state
      isSidebarOpen: true,
      sidebarWidth: 280,

      isWorkflowPanelOpen: true,
      workflowPanelHeight: 300,

      isCommandPaletteOpen: false,

      activeModal: null,

      theme: 'dark',

      isMetricsDashboardOpen: false,

      // Sidebar actions
      toggleSidebar: () =>
        set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),

      setSidebarOpen: (open) =>
        set({ isSidebarOpen: open }),

      setSidebarWidth: (width) =>
        set({ sidebarWidth: Math.max(200, Math.min(400, width)) }),

      // Workflow panel actions
      toggleWorkflowPanel: () =>
        set((state) => ({ isWorkflowPanelOpen: !state.isWorkflowPanelOpen })),

      setWorkflowPanelOpen: (open) =>
        set({ isWorkflowPanelOpen: open }),

      setWorkflowPanelHeight: (height) =>
        set({ workflowPanelHeight: Math.max(200, Math.min(600, height)) }),

      // Command palette actions
      toggleCommandPalette: () =>
        set((state) => ({ isCommandPaletteOpen: !state.isCommandPaletteOpen })),

      setCommandPaletteOpen: (open) =>
        set({ isCommandPaletteOpen: open }),

      // Modal actions
      openModal: (modalId) =>
        set({ activeModal: modalId }),

      closeModal: () =>
        set({ activeModal: null }),

      // Theme actions
      setTheme: (theme) =>
        set({ theme }),

      // Metrics dashboard actions
      toggleMetricsDashboard: () =>
        set((state) => ({ isMetricsDashboardOpen: !state.isMetricsDashboardOpen })),

      setMetricsDashboardOpen: (open) =>
        set({ isMetricsDashboardOpen: open }),
    }),
    {
      name: 'shml-ui-preferences',
      partialize: (state) => ({
        isSidebarOpen: state.isSidebarOpen,
        sidebarWidth: state.sidebarWidth,
        isWorkflowPanelOpen: state.isWorkflowPanelOpen,
        workflowPanelHeight: state.workflowPanelHeight,
        theme: state.theme,
        isMetricsDashboardOpen: state.isMetricsDashboardOpen,
      }),
    }
  )
)
