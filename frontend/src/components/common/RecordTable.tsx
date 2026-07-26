import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { formatValue } from './ValueText'

export function RecordTable({ records, maxColumns = 12, rowKey }: { records: Record<string, unknown>[]; maxColumns?: number; rowKey?: string }) {
  const keys = Array.from(new Set(records.flatMap((record) => Object.keys(record)))).slice(0, maxColumns)
  const columns: ColumnsType<Record<string, unknown>> = keys.map((key) => ({ title: key, dataIndex: key, key, ellipsis: true, render: (value: unknown) => formatValue(value) }))
  return <Table<Record<string, unknown>> size="small" scroll={{ x: 'max-content' }} pagination={{ pageSize: 10, showSizeChanger: true }} dataSource={records.map((record, index) => ({ ...record, __row_key: String(record[rowKey ?? ''] ?? index) }))} columns={columns} rowKey="__row_key" />
}
