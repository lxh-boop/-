import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, DatePicker, Form, InputNumber, Modal, Space, Switch, message } from 'antd'
import { PaperSectionCard } from './PaperSectionCard'
import { paperTradingApi } from '../../api/paperTradingApi'
import { queryKeys } from '../../api/queryKeys'
import { createWriteMeta } from '../../api/writeOperationApi'

export function BackfillPanel({ userId }: { userId: string }) {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: async (values: Record<string, unknown>) => paperTradingApi.previewBackfill({
      ...createWriteMeta('backfill-preview'), user_id:userId,
      start_date:(values.start_date as { format: (pattern: string) => string }).format('YYYY-MM-DD'),
      end_date:values.end_date ? (values.end_date as { format: (pattern: string) => string }).format('YYYY-MM-DD') : 'latest',
      initial_cash: values.initial_cash ? Number(values.initial_cash) : undefined,
      force:Boolean(values.force), resume:Boolean(values.resume),
    }),
    onSuccess:async()=>{message.success('历史回填预案已生成，尚未执行');await queryClient.invalidateQueries({queryKey:queryKeys.paperProposals(userId)})},
    onError:(error)=>message.error(String(error)),
  })
  const submit=async()=>{const values=await form.validateFields();Modal.confirm({title:'生成历史回填预案？',content:'本步骤只生成预案。最终执行将进入可取消、可恢复的 Task Runtime。',okText:'生成预案',onOk:()=>mutation.mutate(values)})}
  return <PaperSectionCard sectionKey="backfill" title="历史模拟盘回填"><Form form={form} layout="vertical" initialValues={{force:true,resume:false}}>
    <Form.Item name="start_date" label="开始日期" rules={[{required:true}]}><DatePicker style={{width:'100%'}} /></Form.Item>
    <Form.Item name="end_date" label="结束日期"><DatePicker style={{width:'100%'}} /></Form.Item>
    <Form.Item name="initial_cash" label="初始资金（可选）"><InputNumber min={1} style={{width:'100%'}} /></Form.Item>
    <Space size="large"><Form.Item name="force" label="覆盖已有区间" valuePropName="checked"><Switch /></Form.Item><Form.Item name="resume" label="断点续跑" valuePropName="checked"><Switch /></Form.Item></Space>
    <Button onClick={submit} loading={mutation.isPending}>生成回填预案</Button>
  </Form></PaperSectionCard>
}
