import { ChartCard } from '../common/ChartCard'
import { SimpleLineChart } from '../common/SimpleLineChart'
import type { RankingRecord } from '../../types/dashboard'
export function ProbabilityChart({ records }: { records: RankingRecord[] }) { const points=records.filter(r=>typeof r.up_prob==='number').slice(0,50).map((r,i)=>({x:String(r.code??i),y:Number(r.up_prob)})); return <ChartCard title="上涨概率"><SimpleLineChart points={points} ariaLabel="上涨概率"/></ChartCard> }
