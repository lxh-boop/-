import { create } from 'zustand'

interface AppState {
  taskDrawerOpen: boolean
  setTaskDrawerOpen: (open: boolean) => void
}

export const useAppStore = create<AppState>((set) => ({
  taskDrawerOpen: false,
  setTaskDrawerOpen: (taskDrawerOpen) => set({ taskDrawerOpen }),
}))
