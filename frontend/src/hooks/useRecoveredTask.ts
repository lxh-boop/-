import { useEffect } from 'react'
import { getTask } from '../api/taskApi'
import { useTaskStore } from '../stores/taskStore'

export function useRecoveredTask() {
  const activeTaskId = useTaskStore((state) => state.activeTaskId)
  const setTask = useTaskStore((state) => state.setTask)

  useEffect(() => {
    if (!activeTaskId) return
    let cancelled = false
    getTask(activeTaskId)
      .then((task) => {
        if (!cancelled) setTask(task)
      })
      .catch(() => {
        if (!cancelled) useTaskStore.getState().clear()
      })
    return () => {
      cancelled = true
    }
  }, [activeTaskId, setTask])
}
