import type { TablePayload } from './common'

export interface DashboardSummary {
  ranking: { available: boolean; total: number; signal_date?: string; prediction_date?: string; updated_at?: string | null }
  model: { backend?: string; version?: string; selected_strategy?: Record<string, unknown>; metrics_available?: boolean }
  backtest: { available: boolean; metrics: Record<string, unknown> }
  news: { available: boolean; total: number }
  feature_flags: Record<string, boolean>
}

export interface RankingRecord {
  code?: string
  name?: string
  rank?: number
  score?: number
  pred_score?: number
  up_prob?: number
  date?: string
  prediction_date?: string
  [key: string]: unknown
}

export type RankingPageData = TablePayload<RankingRecord>

export interface FreshnessItem {
  key: string
  label: string
  status: 'ready' | 'missing' | string
  updated_at: string | null
  size_bytes: number | null
}
