import { ApiContractError } from './errors'
import { decodeTransport } from './transport'
import type { OperationResponse } from '../types/api'

export function unwrapEnvelope<T>(payload: OperationResponse<unknown>): T {
  if (!payload.success) {
    throw new ApiContractError(
      payload.error ?? { code: 'UNKNOWN_ERROR', message: '服务端调用失败' },
      payload.request_id,
    )
  }
  return decodeTransport<T>(payload.data)
}
