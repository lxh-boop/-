import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { TaskEvent, TaskRecord } from '../types/task'

interface TaskState {
  activeTaskId: string
  lastSequence: number
  events: TaskEvent[]
  task: TaskRecord | null
  setTask: (task: TaskRecord | null) => void
  appendEvent: (event: TaskEvent) => void
  clear: () => void
}

export const useTaskStore = create<TaskState>()(
  persist(
    (set) => ({
      activeTaskId: '',
      lastSequence: 0,
      events: [],
      task: null,
      setTask: (task) => set({ activeTaskId: task?.task_id ?? '', task }),
      appendEvent: (event) =>
        set((state) => {
          if (state.events.some((item) => item.sequence === event.sequence)) return state
          return {
            events: [...state.events, event].slice(-200),
            lastSequence: Math.max(state.lastSequence, event.sequence),
          }
        }),
      clear: () => set({ activeTaskId: '', lastSequence: 0, events: [], task: null }),
    }),
    {
      name: 'stock-stage6-task',
      // Only task recovery metadata is persisted. Business results, event payloads,
      // balances and positions must never be written to browser localStorage.
      partialize: (state) => ({
        activeTaskId: state.activeTaskId,
        lastSequence: state.lastSequence,
      }),
    },
  ),
)
