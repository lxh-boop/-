import { ChartCard } from '../common/ChartCard'
import { SimpleLineChart } from '../common/SimpleLineChart'
import type { RankingRecord } from '../../types/dashboard'
export function RankingScoreChart({ records }: { records: RankingRecord[] }) { const points=records.slice(0,50).map((r,i)=>({x:String(r.code??i),y:Number(r.pred_return ?? 0) * 100})); return <ChartCard title="预测涨跌幅分布（%）"><SimpleLineChart points={points} ariaLabel="预测涨跌幅分布"/></ChartCard> }
