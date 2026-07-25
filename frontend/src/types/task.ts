export type TaskStatus =
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timed_out'
  | 'interrupted'

export interface TaskRecord {
  task_id: string
  task_type: string
  status: TaskStatus
  owner_id: string
  session_id: string
  request?: Record<string, unknown>
  metadata?: Record<string, unknown>
  result?: unknown
  error?: unknown
  progress: number
  message: string
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  updated_at: string
  timeout_seconds: number
  max_retries: number
  attempt: number
  cancel_requested: boolean
  worker_pid?: number | null
  acknowledged_at?: string | null
}

export interface TaskEvent {
  sequence: number
  task_id: string
  event_type: string
  data: Record<string, unknown>
  created_at: string
}

export interface TaskSubmitRequest {
  task_type: string
  args?: unknown[]
  kwargs?: Record<string, unknown>
  owner_id?: string
  session_id?: string
  metadata?: Record<string, unknown>
  timeout_seconds?: number
  max_retries?: number
}

export const TERMINAL_TASK_STATUSES: ReadonlySet<TaskStatus> = new Set([
  'succeeded',
  'failed',
  'cancelled',
  'timed_out',
  'interrupted',
])
