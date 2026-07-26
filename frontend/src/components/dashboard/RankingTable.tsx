import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { RankingRecord } from '../../types/dashboard'
const number = (value: unknown) => typeof value === 'number' ? value.toFixed(4) : String(value ?? '—')
export function RankingTable({ records, onSelect }: { records: RankingRecord[]; onSelect?: (code: string) => void }) {
  const columns: ColumnsType<RankingRecord> = [
    { title: '排名', dataIndex: 'rank', width: 76, render: (value, _row, index) => value ?? index + 1 },
    { title: '股票代码', dataIndex: 'code', width: 110, render: (value) => <a onClick={() => onSelect?.(String(value))}>{String(value ?? '')}</a> },
    { title: '股票名称', dataIndex: 'name', width: 120 },
    { title: '模型分数', dataIndex: 'pred_score', render: (value, row) => number(value ?? row.raw_score ?? row.pred_5d_ret) },
    { title: '综合分', dataIndex: 'score', render: number },
    { title: '上涨概率', dataIndex: 'up_prob', render: (value) => typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '—' },
    { title: '信号日期', dataIndex: 'date', render: (value) => <Tag>{String(value ?? '—').slice(0,10)}</Tag> },
  ]
  return <Table<RankingRecord> size="middle" scroll={{ x: 900 }} pagination={{ pageSize: 20, showSizeChanger: true }} dataSource={records} columns={columns} rowKey={(row) => `${String(row.code ?? '')}-${String(row.rank ?? '')}-${String(row.name ?? '')}`} />
}
