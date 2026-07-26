import { getWeb } from './webApi'
import type { MonitorServices, MonitorSummary, MonitorTable } from '../types/monitor'
export const monitorApi = {
  summary: (userId = 'default') => getWeb<MonitorSummary>('/api/v1/web/monitor/summary', { params: { user_id: userId } }),
  services: (userId = 'default') => getWeb<MonitorServices>('/api/v1/web/monitor/services', { params: { user_id: userId } }),
  history: (userId = 'default', limit = 30) => getWeb<MonitorTable>('/api/v1/web/monitor/history', { params: { user_id: userId, limit } }),
  alerts: (userId = 'default', limit = 100) => getWeb<MonitorTable>('/api/v1/web/monitor/alerts', { params: { user_id: userId, limit } }),
}
