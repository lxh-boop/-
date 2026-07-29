import { ChartCard } from '../common/ChartCard'
import { SimpleLineChart } from '../common/SimpleLineChart'
export function BacktestNavChart({ records }: { records: Record<string, unknown>[] }) { const points=records.map((r,i)=>({x:String(r.date??i).slice(0,10),y:Number(r.nav??r.strategy_nav??0)})); return <ChartCard title="回测净值"><SimpleLineChart points={points} ariaLabel="回测净值"/></ChartCard> }
