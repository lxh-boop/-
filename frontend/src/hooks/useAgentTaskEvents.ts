import { useEffect } from 'react'
import { connectTaskEvents } from '../api/taskSse'
import { TERMINAL_TASK_STATUSES } from '../types/task'
import { useAgentTaskStore } from '../stores/agentTaskStore'

export function useAgentTaskEvents() {
  const taskId = useAgentTaskStore((state) => state.taskId)
  const status = useAgentTaskStore((state) => state.task?.status)
  const appendEvent = useAgentTaskStore((state) => state.appendEvent)
  const setTask = useAgentTaskStore((state) => state.setTask)

  useEffect(() => {
    if (!taskId || (status && TERMINAL_TASK_STATUSES.has(status))) return
    const after = useAgentTaskStore.getState().lastSequence
    return connectTaskEvents(taskId, after, {
      onEvent: (event) => {
        appendEvent(event)
        const current = useAgentTaskStore.getState().task
        const progress = Number(event.data.progress)
        const message = typeof event.data.message === 'string' ? event.data.message : undefined
        if (current) {
          setTask({
            ...current,
            status: event.event_type === 'started' ? 'running' : current.status,
            progress: Number.isFinite(progress) ? progress : current.progress,
            message: message ?? current.message,
          })
        }
      },
      onComplete: setTask,
      onError: () => {
        // The task is still recoverable with task_id; polling in AgentPage continues.
      },
    })
  }, [appendEvent, setTask, status, taskId])
}
