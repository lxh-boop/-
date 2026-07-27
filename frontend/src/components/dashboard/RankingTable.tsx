import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { RankingRecord } from '../../types/dashboard'

const number = (value: unknown) => typeof value === 'number' ? value.toFixed(4) : String(value ?? '—')
const price = (value: unknown) => typeof value === 'number' ? value.toFixed(2) : '—'

export function RankingTable({ records, onSelect }: { records: RankingRecord[]; onSelect?: (code: string) => void }) {
  const columns: ColumnsType<RankingRecord> = [
    { title: '排名', dataIndex: 'rank', width: 70, fixed: 'left', render: (value, _row, index) => value ?? index + 1 },
    { title: '股票代码', dataIndex: 'code', width: 105, fixed: 'left', render: (value) => <a onClick={() => onSelect?.(String(value))}>{String(value ?? '')}</a> },
    { title: '股票名称', dataIndex: 'name', width: 115, fixed: 'left' },
    { title: '模型分数', dataIndex: 'pred_score', width: 110, render: (value, row) => number(value ?? row.raw_score ?? row.pred_5d_ret) },
    { title: '综合分', dataIndex: 'score', width: 100, render: number },
    { title: '上涨概率', dataIndex: 'up_prob', width: 110, render: (value) => typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '—' },
    { title: '开盘价', dataIndex: 'open', width: 95, render: price },
    { title: '最高价', dataIndex: 'high', width: 95, render: price },
    { title: '最低价', dataIndex: 'low', width: 95, render: price },
    { title: '收盘价', dataIndex: 'close', width: 95, render: price },
    { title: '信号日期', dataIndex: 'date', width: 125, render: (value, row) => <Tag color={row.ohlc_available ? 'default' : 'warning'}>{String(value ?? '—').slice(0, 10)}</Tag> },
  ]
  return <Table<RankingRecord> size="middle" scroll={{ x: 1250 }} pagination={{ pageSize: 20, showSizeChanger: true }} dataSource={records} columns={columns} rowKey={(row) => `${String(row.code ?? '')}-${String(row.rank ?? '')}-${String(row.name ?? '')}`} />
}
