import { httpClient } from './httpClient'
import { unwrapEnvelope } from './envelope'
import { getWeb } from './webApi'
import type { OperationResponse } from '../types/api'
import type { PublicSettings, SettingsUpdateRequest, SettingsUpdateResult } from '../types/settings'

export const settingsApi = {
  get: () => getWeb<PublicSettings>('/api/v1/web/settings'),
  update: async (payload: SettingsUpdateRequest): Promise<SettingsUpdateResult> => {
    const response = await httpClient.put<OperationResponse<unknown>>('/api/v1/web/settings', payload)
    return unwrapEnvelope<SettingsUpdateResult>(response.data)
  },
}
