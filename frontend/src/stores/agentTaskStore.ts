import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { TaskEvent, TaskRecord } from '../types/task'

interface AgentTaskState {
  taskId: string
  conversationId: string
  lastSequence: number
  task: TaskRecord | null
  events: TaskEvent[]
  setRecovery: (taskId: string, conversationId: string) => void
  setTask: (task: TaskRecord | null) => void
  appendEvent: (event: TaskEvent) => void
  clear: () => void
}

export const useAgentTaskStore = create<AgentTaskState>()(
  persist(
    (set) => ({
      taskId: '',
      conversationId: '',
      lastSequence: 0,
      task: null,
      events: [],
      setRecovery: (taskId, conversationId) =>
        set({ taskId, conversationId, lastSequence: 0, task: null, events: [] }),
      setTask: (task) =>
        set((state) => ({
          task,
          taskId: task?.task_id ?? state.taskId,
          conversationId: task?.session_id ?? state.conversationId,
        })),
      appendEvent: (event) =>
        set((state) => {
          if (state.events.some((item) => item.sequence === event.sequence)) return state
          return {
            events: [...state.events, event].slice(-200),
            lastSequence: Math.max(state.lastSequence, event.sequence),
          }
        }),
      clear: () =>
        set({ taskId: '', conversationId: '', lastSequence: 0, task: null, events: [] }),
    }),
    {
      name: 'stock-stage6-agent-task',
      // Persist only identifiers needed to reconnect after refresh.
      partialize: (state) => ({
        taskId: state.taskId,
        conversationId: state.conversationId,
        lastSequence: state.lastSequence,
      }),
    },
  ),
)
