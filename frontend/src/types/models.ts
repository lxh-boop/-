import type { TablePayload } from './common'
export interface ModelMetricsData { metrics: Record<string, unknown>; selected_strategy: Record<string, unknown> }
export interface ModelSearchResults {
  candidates: TablePayload
  master_backtests: TablePayload
  target_results: TablePayload
  errors: TablePayload
  selected_strategy: Record<string, unknown>
  discovery_report: string
  read_only: true
}
