import { Button } from 'antd'
import type { TaskRecord } from '../../types/task'
import { TERMINAL_TASK_STATUSES } from '../../types/task'

export function CancelTaskButton({ task, loading, onCancel }: { task: TaskRecord; loading: boolean; onCancel: () => void }) {
  if (TERMINAL_TASK_STATUSES.has(task.status)) return null
  return <Button danger loading={loading} onClick={onCancel}>取消任务</Button>
}
