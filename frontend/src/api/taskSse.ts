import { decodeTransport } from './transport'
import type { TaskEvent, TaskRecord } from '../types/task'

export interface TaskSseCallbacks {
  onEvent: (event: TaskEvent) => void
  onComplete: (task: TaskRecord) => void
  onError?: (message: string) => void
}

export function connectTaskEvents(
  taskId: string,
  after: number,
  callbacks: TaskSseCallbacks,
): () => void {
  const url = `/api/v1/tasks/${encodeURIComponent(taskId)}/events?after=${Math.max(0, after)}`
  const source = new EventSource(url)
  let completed = false

  source.addEventListener('task-event', (raw) => {
    const message = raw as MessageEvent<string>
    const event = decodeTransport<TaskEvent>(JSON.parse(message.data))
    callbacks.onEvent(event)
  })

  source.addEventListener('task-complete', (raw) => {
    const message = raw as MessageEvent<string>
    const payload = decodeTransport<{ task: TaskRecord }>(JSON.parse(message.data))
    completed = true
    callbacks.onComplete(payload.task)
    source.close()
  })

  source.onerror = () => {
    if (!completed && source.readyState === EventSource.CLOSED) {
      callbacks.onError?.('SSE 连接已关闭，可通过 task_id 继续恢复')
    }
  }

  return () => source.close()
}
