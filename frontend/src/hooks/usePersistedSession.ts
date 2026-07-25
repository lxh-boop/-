import { useSessionStore } from '../stores/sessionStore'

export function usePersistedSession() {
  return useSessionStore()
}
