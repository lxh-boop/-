import { ChartCard } from '../common/ChartCard'
import { SimpleLineChart } from '../common/SimpleLineChart'
export function StockPriceChart({ records }: { records: Record<string, unknown>[] }) { const points=records.map((r,i)=>({x:String(r.date??i).slice(0,10),y:Number(r.close??r.price??0)})); return <ChartCard title="历史价格"><SimpleLineChart points={points} ariaLabel="股票历史价格"/></ChartCard> }
