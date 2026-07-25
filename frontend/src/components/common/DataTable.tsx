import { Table, type TableProps } from 'antd'
export function DataTable<T extends object>(props: TableProps<T>) { return <Table<T> size="middle" pagination={{ pageSize: 10 }} {...props} /> }
