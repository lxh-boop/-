import { Empty, Table, Tag, Typography } from 'antd'
import type { AgentStrategyProposal } from '../../types/agent'

export function StrategyProposalPanel({ data }: { data?: AgentStrategyProposal }) {
  if (!data?.available || !data.proposal) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前会话没有策略草稿" />
  }
  const current = data.proposal
  return <>
    <Typography.Paragraph>
      <Tag color="blue">只读草稿</Tag>
      当前版本：{String(current.current_version ?? '-')} · 状态：{String(current.status ?? '-')}
    </Typography.Paragraph>
    <Table
      size="small"
      pagination={false}
      rowKey={(row) => `${String(row.proposal_id ?? '')}-${String(row.version ?? '')}`}
      dataSource={data.versions}
      columns={[
        { title: '版本', dataIndex: 'version', width: 90 },
        { title: '修改摘要', dataIndex: 'change_summary' },
        { title: '用户反馈', dataIndex: 'user_feedback' },
        { title: '创建时间', dataIndex: 'created_at', width: 180 },
      ]}
    />
    <Typography.Text type="secondary">
      该面板只用于继续讨论，不提供绕过 WriteGateway 的正式应用入口。
    </Typography.Text>
  </>
}
