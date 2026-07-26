import { Select } from 'antd'
import type { RankingRecord } from '../../types/dashboard'
export function StockSelector({ records, value, onChange }: { records: RankingRecord[]; value?: string; onChange: (code: string) => void }) { return <Select showSearch optionFilterProp="label" style={{ minWidth: 280 }} placeholder="选择股票" value={value} onChange={onChange} options={records.map((r)=>({value:String(r.code??''),label:`${r.code ?? ''} ${r.name ?? ''}`})).filter(o=>o.value)} /> }
