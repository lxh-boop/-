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
  raw_score?: number
  pred_5d_ret?: number
  up_prob?: number
  up_prob_calibrated?: number
  calibrated?: boolean
  calibration_method?: string
  calibration_sample_count?: number
  calibration_positive_count?: number
  calibration_positive_rate?: number
  calibration_start_date?: string
  calibration_end_date?: string
  calibration_target?: string
  calibration_horizon_days?: number
  calibration_top_k?: number
  calibration_brier_score?: number
  calibration_log_loss?: number
  open?: number
  high?: number
  low?: number
  close?: number
  ohlc_available?: boolean
  date?: string
  prediction_date?: string
  [key: string]: unknown
}

export interface Top15Statistics {
  top5_daily_average_up_rate?: number
  top10_daily_average_up_rate?: number
  daily_average_up_rate?: number
  observation_days?: number
  complete_days?: number
  observation_count?: number
  rise_count?: number
  top_k?: number
  start_date?: string
  end_date?: string
  target?: string
}

export interface RankingPageData extends TablePayload<RankingRecord> {
  top15_statistics?: Top15Statistics | null
}

export interface FreshnessItem {
  key: string
  label: string
  status: 'ready' | 'missing' | string
  updated_at: string | null
  size_bytes: number | null
}
