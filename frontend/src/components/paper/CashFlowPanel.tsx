import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, DatePicker, Form, Input, InputNumber, Modal, Radio, Space, message } from 'antd'
import { PaperSectionCard } from './PaperSectionCard'
import { paperTradingApi } from '../../api/paperTradingApi'
import { queryKeys } from '../../api/queryKeys'
import { createWriteMeta } from '../../api/writeOperationApi'

export function CashFlowPanel({ userId }: { userId: string }) {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: async (values: Record<string, unknown>) => paperTradingApi.previewCashFlow({
      ...createWriteMeta('cash-flow-preview'), user_id: userId,
      flow_type: values.flow_type as 'deposit' | 'withdrawal', amount: Number(values.amount),
      effective_date: typeof (values.effective_date as { format?: (pattern: string) => string } | undefined)?.format === 'function' ? (values.effective_date as { format: (pattern: string) => string }).format('YYYY-MM-DD') : undefined, reason: String(values.reason ?? ''),
    }),
    onSuccess: async () => {
      message.success('资金变更预案已生成，尚未修改账户')
      await queryClient.invalidateQueries({ queryKey: queryKeys.paperProposals(userId) })
    },
    onError: (error) => message.error(String(error)),
  })
  const submit = async () => {
    const values = await form.validateFields()
    Modal.confirm({ title: '生成资金变更预案？', content: '本步骤只生成可核对的预案，不会直接修改模拟盘账户。', okText: '生成预案', onOk: () => mutation.mutate(values) })
  }
  return <PaperSectionCard sectionKey="cash-flow" title="资金管理"><Form form={form} layout="vertical" initialValues={{ flow_type: 'deposit' }}>
    <Form.Item name="flow_type" label="操作" rules={[{ required: true }]}><Radio.Group options={[{value:'deposit',label:'入金'},{value:'withdrawal',label:'出金'}]} /></Form.Item>
    <Form.Item name="amount" label="金额（元）" rules={[{ required: true }]}><InputNumber min={0.01} precision={2} style={{width:'100%'}} /></Form.Item>
    <Form.Item name="effective_date" label="生效日期" rules={[{ required: true }]}><DatePicker style={{width:'100%'}} /></Form.Item>
    <Form.Item name="reason" label="原因"><Input.TextArea rows={2} maxLength={300} /></Form.Item>
    <Space><Button onClick={submit} loading={mutation.isPending}>生成预案</Button></Space>
  </Form></PaperSectionCard>
}
