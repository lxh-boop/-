import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SessionState {
  ownerId: string
  sessionId: string
  setOwnerId: (value: string) => void
  rotateSession: () => void
}

function randomSessionId(): string {
  return `react-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      ownerId: 'refactor_test',
      sessionId: randomSessionId(),
      setOwnerId: (ownerId) => set({ ownerId: ownerId.trim() || 'refactor_test' }),
      rotateSession: () => set({ sessionId: randomSessionId() }),
    }),
    { name: 'stock-stage6-session' },
  ),
)
