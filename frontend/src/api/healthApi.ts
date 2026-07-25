import { httpClient } from './httpClient'
import { unwrapEnvelope } from './envelope'
import type { HealthData, OperationResponse } from '../types/api'

export async function fetchHealth(): Promise<HealthData> {
  const response = await httpClient.get<OperationResponse<unknown>>('/api/v1/health')
  return unwrapEnvelope<HealthData>(response.data)
}
