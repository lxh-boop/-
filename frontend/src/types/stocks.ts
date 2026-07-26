import type { TablePayload } from './common'

export interface StockDetail {
  stock_code: string
  name: string
  ranking: Record<string, unknown>
  market: Record<string, unknown>
  event_count: number
  found: boolean
}

export type StockHistory = TablePayload<Record<string, unknown>> & { stock_code: string }
export type StockEvidence = TablePayload<Record<string, unknown>> & { stock_code: string; query: string; warning?: string | null }
export interface StockExplanation { stock_code: string; available: boolean; cached: unknown; generated: false; message: string }
