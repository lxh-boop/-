import { ChartCard } from '../common/ChartCard'
import { SimpleLineChart } from '../common/SimpleLineChart'
import type { RankingRecord } from '../../types/dashboard'

export function ProbabilityChart({ records }: { records: RankingRecord[] }) {
  const points = records
    .filter((record) => record.calibrated === true && typeof record.up_prob_calibrated === 'number')
    .slice(0, 50)
    .map((record, index) => ({
      x: String(record.code ?? index),
      y: Number(record.up_prob_calibrated),
    }))
  return <ChartCard title="该股预测上涨后平滑真实上涨率"><SimpleLineChart points={points} ariaLabel="该股预测上涨后平滑真实上涨率"/></ChartCard>
}
