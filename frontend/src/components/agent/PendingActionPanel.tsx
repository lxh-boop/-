import { Button, Card, Empty, Input, List, Modal, Space, Tag, Typography, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { agentApi } from '../../api/agentApi'
import type { AgentPendingAction } from '../../types/agent'

function uniqueId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function PendingActionPanel({
  userId,
  conversationId,
  actions,
}: {
  userId: string
  conversationId: string
  actions: AgentPendingAction[]
}) {
  const queryClient = useQueryClient()
  const confirm = useMutation({
    mutationFn: async ({ item, text }: { item: AgentPendingAction; text: string }) =>
      agentApi.confirmPendingAction(
        userId,
        conversationId,
        item.plan_id,
        text,
        uniqueId('agent-confirm'),
        uniqueId('agent-confirm-idem'),
      ),
    onSuccess: async () => {
      message.success('待确认操作已提交')
      await queryClient.invalidateQueries({ queryKey: ['web', 'agent', 'pending', userId, conversationId] })
    },
    onError: (error) => message.error(String(error)),
  })
  const reject = useMutation({
    mutationFn: async (item: AgentPendingAction) =>
      agentApi.rejectPendingAction(
        userId,
        conversationId,
        item.plan_id,
        uniqueId('agent-reject'),
        uniqueId('agent-reject-idem'),
      ),
    onSuccess: async () => {
      message.success('计划已拒绝，业务状态未写入')
      await queryClient.invalidateQueries({ queryKey: ['web', 'agent', 'pending', userId, conversationId] })
    },
    onError: (error) => message.error(String(error)),
  })

  const openConfirm = (item: AgentPendingAction) => {
    let typed = ''
    Modal.confirm({
      title: '确认执行 Agent 待确认操作？',
      width: 620,
      okText: '确认执行',
      cancelText: '取消',
      content: <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Paragraph>
          该操作仍由服务端 WriteGateway 重新校验。请输入：
          <Typography.Text code>{item.confirmation_phrase}</Typography.Text>
        </Typography.Paragraph>
        <Input onChange={(event) => { typed = event.target.value }} placeholder={item.confirmation_phrase} />
      </Space>,
      onOk: async () => {
        if (typed.trim().toUpperCase() !== item.confirmation_phrase.toUpperCase()) {
          throw new Error('确认短语不一致')
        }
        await confirm.mutateAsync({ item, text: typed })
      },
    })
  }

  if (!actions.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前会话没有待确认操作" />
  }

  return <List
    dataSource={actions}
    renderItem={(item) => <List.Item>
      <Card
        size="small"
        style={{ width: '100%' }}
        title={<Space><Tag color="orange">等待确认</Tag><Typography.Text>{item.operation_type || item.intent}</Typography.Text></Space>}
        extra={<Typography.Text type="secondary">{item.created_at}</Typography.Text>}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text>计划：{item.plan_id}</Typography.Text>
          <pre className="agent-json-block">{JSON.stringify({
            before: item.before_state_summary,
            changes: item.proposed_changes,
            after: item.after_state_preview,
            warnings: item.warnings,
          }, null, 2)}</pre>
          <Space>
            <Button type="primary" loading={confirm.isPending} onClick={() => openConfirm(item)}>确认</Button>
            <Button danger loading={reject.isPending} onClick={() => {
              Modal.confirm({
                title: '拒绝该计划？',
                content: '拒绝后不会执行模拟盘写操作。',
                okText: '拒绝',
                cancelText: '取消',
                onOk: () => reject.mutateAsync(item),
              })
            }}>拒绝</Button>
          </Space>
        </Space>
      </Card>
    </List.Item>}
  />
}
