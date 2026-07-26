import { ChartCard } from '../common/ChartCard'
import { SimpleLineChart } from '../common/SimpleLineChart'
import type { RankingRecord } from '../../types/dashboard'
export function RankingScoreChart({ records }: { records: RankingRecord[] }) { const points=records.slice(0,50).map((r,i)=>({x:String(r.code??i),y:Number(r.pred_score ?? r.raw_score ?? r.pred_5d_ret ?? r.score ?? 0)})); return <ChartCard title="排名分数分布"><SimpleLineChart points={points} ariaLabel="排名分数分布"/></ChartCard> }
