import { Table, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { RankingRecord } from '../../types/dashboard'

const price = (value: unknown) => typeof value === 'number' ? value.toFixed(2) : '—'
const percent = (value: unknown) => typeof value === 'number' ? <Tag color={value > 0 ? 'green' : value < 0 ? 'red' : 'default'}>{(value * 100).toFixed(2)}%</Tag> : '—'

function calibratedProbability(value: unknown, row: RankingRecord) {
  if (row.calibrated !== true || typeof value !== 'number') {
    return <Tag color="warning">暂无前15样本</Tag>
  }
  const samples = Number(row.calibration_sample_count ?? 0)
  const rises = Number(row.calibration_positive_count ?? 0)
  const dateRange = row.calibration_start_date && row.calibration_end_date
    ? `${row.calibration_start_date} 至 ${row.calibration_end_date}`
    : '历史已实现区间'
  const detail = `${row.code ?? '该股票'} 在 ${dateRange} 共进入每日前15名 ${samples.toLocaleString()} 次，其中下一交易日实际上涨 ${rises.toLocaleString()} 次`
  return <Tooltip title={detail}><span>{(value * 100).toFixed(2)}%</span></Tooltip>
}

export function RankingTable({ records, onSelect }: { records: RankingRecord[]; onSelect?: (code: string) => void }) {
  const columns: ColumnsType<RankingRecord> = [
    { title: '排名', dataIndex: 'rank', width: 70, fixed: 'left', render: (value, _row, index) => value ?? index + 1 },
    { title: '股票代码', dataIndex: 'code', width: 105, fixed: 'left', render: (value) => <a onClick={() => onSelect?.(String(value))}>{String(value ?? '')}</a> },
    { title: '股票名称', dataIndex: 'name', width: 115, fixed: 'left' },
    { title: '预测涨跌幅', dataIndex: 'pred_return', width: 120, render: percent },
    { title: '该股前15后次日上涨概率', dataIndex: 'up_prob_calibrated', width: 200, render: calibratedProbability },
    { title: '预测开盘', dataIndex: 'pred_open', width: 105, render: price },
    { title: '预测最高', dataIndex: 'pred_high', width: 105, render: price },
    { title: '预测最低', dataIndex: 'pred_low', width: 105, render: price },
    { title: '预测收盘', dataIndex: 'pred_close', width: 105, render: price },
    { title: '当前收盘', dataIndex: 'close', width: 105, render: price },
    { title: '预测日期', dataIndex: 'prediction_date', width: 125, render: (value) => <Tag color="blue">{String(value ?? '—').slice(0, 10)}</Tag> },
    { title: '信号日期', dataIndex: 'date', width: 125, render: (value, row) => <Tag color={row.ohlc_available ? 'default' : 'warning'}>{String(value ?? '—').slice(0, 10)}</Tag> },
  ]
  return <Table<RankingRecord> size="middle" scroll={{ x: 1250 }} pagination={{ pageSize: 20, showSizeChanger: true }} dataSource={records} columns={columns} rowKey={(row) => `${String(row.code ?? '')}-${String(row.rank ?? '')}-${String(row.name ?? '')}`} />
}
