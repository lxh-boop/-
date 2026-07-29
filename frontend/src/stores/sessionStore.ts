import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import {
  migrateOwnerIdentity,
  normalizeOwnerId,
  SYSTEM_OWNER_FALLBACK,
  type OwnerMode,
} from './sessionIdentity'

interface SessionState {
  ownerId: string
  ownerMode: OwnerMode
  sessionId: string
  setOwnerId: (value: string) => void
  useSystemOwnerId: (value: string) => void
  rotateSession: () => void
}

function randomSessionId(): string {
  return `react-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      ownerId: SYSTEM_OWNER_FALLBACK,
      ownerMode: 'system',
      sessionId: randomSessionId(),
      setOwnerId: (ownerId) => set({ ownerId: normalizeOwnerId(ownerId), ownerMode: 'manual' }),
      useSystemOwnerId: (ownerId) => set({ ownerId: normalizeOwnerId(ownerId), ownerMode: 'system' }),
      rotateSession: () => set({ sessionId: randomSessionId() }),
    }),
    {
      name: 'stock-stage6-session',
      version: 2,
      migrate: (persistedState, version) => {
        const state = (persistedState ?? {}) as Partial<SessionState>
        if (version >= 2 && state.ownerMode) {
          return {
            ...state,
            ownerId: normalizeOwnerId(state.ownerId),
            ownerMode: state.ownerMode,
            sessionId: String(state.sessionId || randomSessionId()),
          }
        }
        const identity = migrateOwnerIdentity(state.ownerId)
        return {
          ...state,
          ...identity,
          sessionId: String(state.sessionId || randomSessionId()),
        }
      },
    },
  ),
)
