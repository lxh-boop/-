import { useEffect } from 'react'
import { connectTaskEvents } from '../api/taskSse'
import { TERMINAL_TASK_STATUSES } from '../types/task'
import { useTaskStore } from '../stores/taskStore'

export function useTaskEvents() {
  const activeTaskId = useTaskStore((state) => state.activeTaskId)
  const taskStatus = useTaskStore((state) => state.task?.status)
  const appendEvent = useTaskStore((state) => state.appendEvent)
  const setTask = useTaskStore((state) => state.setTask)

  useEffect(() => {
    if (!activeTaskId || (taskStatus && TERMINAL_TASK_STATUSES.has(taskStatus))) return
    const after = useTaskStore.getState().lastSequence
    return connectTaskEvents(activeTaskId, after, {
      onEvent: (event) => {
        appendEvent(event)
        const current = useTaskStore.getState().task
        const progress = Number(event.data.progress)
        const message = typeof event.data.message === 'string' ? event.data.message : undefined
        if (current && (Number.isFinite(progress) || message || event.event_type === 'started')) {
          const status = event.event_type === 'started' ? 'running' : current.status
          setTask({
            ...current,
            status,
            progress: Number.isFinite(progress) ? progress : current.progress,
            message: message ?? current.message,
          })
        }
      },
      onComplete: setTask,
    })
  }, [activeTaskId, appendEvent, setTask, taskStatus])
}
