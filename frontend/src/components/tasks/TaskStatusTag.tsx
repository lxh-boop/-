import { Tag } from 'antd'
import type { TaskStatus } from '../../types/task'

const colors: Record<TaskStatus, string> = {
  queued: 'default', running: 'processing', cancelling: 'warning', succeeded: 'success',
  failed: 'error', cancelled: 'default', timed_out: 'error', interrupted: 'warning',
}

export function TaskStatusTag({ status }: { status: TaskStatus }) {
  return <Tag color={colors[status]} data-testid="task-status">{status}</Tag>
}
