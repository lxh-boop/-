export interface ApiErrorPayload {
  code: string
  message: string
  details?: Record<string, unknown>
}

export interface OperationResponse<T = unknown> {
  success: boolean
  data: T | null
  error: ApiErrorPayload | null
  request_id: string
}

export interface HealthData {
  status: string
  service: string
  version: string
  deployment_mode: string
  project_root: string
}
