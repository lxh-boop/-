import type { AxiosRequestConfig } from 'axios'
import { httpClient } from './httpClient'
import { unwrapEnvelope } from './envelope'
import type { OperationResponse } from '../types/api'

export async function getWeb<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.get<OperationResponse<unknown>>(url, config)
  return unwrapEnvelope<T>(response.data)
}
