import type { ApiErrorPayload } from '../types/api'

export class ApiContractError extends Error {
  readonly code: string
  readonly details: Record<string, unknown>
  readonly requestId: string

  constructor(error: ApiErrorPayload, requestId = '') {
    super(error.message || '服务端返回未知错误')
    this.name = 'ApiContractError'
    this.code = error.code || 'UNKNOWN_ERROR'
    this.details = error.details ?? {}
    this.requestId = requestId
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error ?? '未知错误')
}
