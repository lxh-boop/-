import type { TablePayload } from './common'
export interface BacktestDetail { backtest_id: string; available: boolean; metrics: Record<string, unknown> }
export type BacktestTable = TablePayload<Record<string, unknown>>
