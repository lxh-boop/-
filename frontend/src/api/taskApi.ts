import { httpClient } from './httpClient'
import { unwrapEnvelope } from './envelope'
import { encodeTransport } from './transport'
import type { OperationResponse } from '../types/api'
import type { TaskRecord, TaskSubmitRequest } from '../types/task'

export async function submitTask(request: TaskSubmitRequest): Promise<TaskRecord> {
  const response = await httpClient.post<OperationResponse<unknown>>('/api/v1/tasks', {
    ...request,
    args: encodeTransport(request.args ?? []),
    kwargs: encodeTransport(request.kwargs ?? {}),
    metadata: encodeTransport(request.metadata ?? {}),
  })
  return unwrapEnvelope<TaskRecord>(response.data)
}

export async function getTask(taskId: string): Promise<TaskRecord> {
  const response = await httpClient.get<OperationResponse<unknown>>(`/api/v1/tasks/${encodeURIComponent(taskId)}`)
  return unwrapEnvelope<TaskRecord>(response.data)
}

export async function cancelTask(taskId: string): Promise<TaskRecord> {
  const response = await httpClient.post<OperationResponse<unknown>>(`/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`)
  return unwrapEnvelope<TaskRecord>(response.data)
}

export async function acknowledgeTask(taskId: string): Promise<TaskRecord> {
  const response = await httpClient.post<OperationResponse<unknown>>(`/api/v1/tasks/${encodeURIComponent(taskId)}/acknowledge`)
  return unwrapEnvelope<TaskRecord>(response.data)
}

export interface TaskListParams {
  owner_id?: string
  session_id?: string
  task_type?: string
  active_only?: boolean
  unacknowledged_only?: boolean
  limit?: number
}

export async function listTasks(params: TaskListParams = {}): Promise<TaskRecord[]> {
  const response = await httpClient.get<OperationResponse<unknown>>('/api/v1/tasks', { params })
  return unwrapEnvelope<TaskRecord[]>(response.data)
}
