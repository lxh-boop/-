import { Card } from 'antd'
import { RecordTable } from '../common/RecordTable'
export function BacktestTradeTable({ records }: { records: Record<string, unknown>[] }) { return <Card title="交易与持仓明细"><RecordTable records={records} maxColumns={16}/></Card> }
