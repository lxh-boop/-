import { Card, Col, Row, Tabs } from 'antd'
import { RecordTable } from '../common/RecordTable'
import { PaperSectionCard } from './PaperSectionCard'
import type { TablePayload } from '../../types/common'

export function PaperTables({ positions, orders, decisions, cashFlows }: {
  positions: TablePayload<Record<string, unknown>>
  orders: TablePayload<Record<string, unknown>>
  decisions: TablePayload<Record<string, unknown>>
  cashFlows: TablePayload<Record<string, unknown>>
}) {
  return <PaperSectionCard sectionKey="paper-records" title="持仓、订单与决策记录"><Tabs items={[
    { key: 'positions', label: `当前持仓 (${positions.total})`, children: <RecordTable records={positions.records} rowKey="stock_code" /> },
    { key: 'orders', label: `订单历史 (${orders.total})`, children: <RecordTable records={orders.records} /> },
    { key: 'decisions', label: `当日决策 (${decisions.total})`, children: <RecordTable records={decisions.records} rowKey="stock_code" /> },
    { key: 'cash', label: `资金流水 (${cashFlows.total})`, children: <RecordTable records={cashFlows.records} /> },
  ]} /></PaperSectionCard>
}

export function RiskAndDiagnostics({ risk, diagnostics, settings }: { risk: Record<string, unknown>; diagnostics: Record<string, unknown>; settings: Record<string, unknown> }) {
  return <PaperSectionCard sectionKey="risk-diagnostics" title="风险、执行诊断与交易设置">
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={8}><Card size="small" title="组合风险"><RecordTable records={[risk]} maxColumns={16} /></Card></Col>
      <Col xs={24} xl={8}><Card size="small" title="执行诊断"><RecordTable records={[diagnostics]} maxColumns={16} /></Card></Col>
      <Col xs={24} xl={8}><Card size="small" title="交易设置"><RecordTable records={[settings]} maxColumns={16} /></Card></Col>
    </Row>
  </PaperSectionCard>
}
