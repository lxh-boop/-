import { PaperSectionCard } from './PaperSectionCard'
import { SimpleLineChart } from '../common/SimpleLineChart'
import type { TablePayload } from '../../types/common'

function valueOf(record: Record<string, unknown>): number {
  for (const key of ['total_assets', 'nav', 'account_value', 'total_asset']) {
    const value = Number(record[key])
    if (Number.isFinite(value)) return value
  }
  return Number.NaN
}

function dateOf(record: Record<string, unknown>, index: number): string {
  return String(record.trade_date ?? record.date ?? record.created_at ?? index)
}

export function AssetCurve({ data }: { data: TablePayload<Record<string, unknown>> }) {
  const points = (data.records ?? []).map((record, index) => ({ x: dateOf(record, index), y: valueOf(record) }))
  return <PaperSectionCard sectionKey="asset-curve" title="账户资产走势"><SimpleLineChart points={points} ariaLabel="模拟盘账户资产走势" /></PaperSectionCard>
}
