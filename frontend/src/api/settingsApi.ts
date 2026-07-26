import { getWeb } from './webApi'
import type { PublicSettings } from '../types/settings'
export const settingsApi = { get: () => getWeb<PublicSettings>('/api/v1/web/settings') }
