import { Card } from 'antd'
import { RecordTable } from '../common/RecordTable'
export function EventFactorTable({ records }: { records: Record<string, unknown>[] }) { return <Card title="事件与证据"><RecordTable records={records}/></Card> }
