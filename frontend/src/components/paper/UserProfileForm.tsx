import { useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, Checkbox, Col, Form, Input, InputNumber, Modal, Row, Select, Space, Tag, message } from 'antd'
import { PaperSectionCard } from './PaperSectionCard'
import { paperTradingApi } from '../../api/paperTradingApi'
import { queryKeys } from '../../api/queryKeys'
import { createWriteMeta } from '../../api/writeOperationApi'

interface Props {
  userId: string
  profile: Record<string, unknown>
  options: Record<string, string[]>
  complete: boolean
}

const fields = [
  ['age_range', '年龄范围'], ['income_stability', '收入稳定性'], ['investment_experience', '投资经验'],
  ['liquidity_need', '流动性需求'], ['risk_level', '风险等级'], ['max_drawdown_tolerance', '最大回撤容忍'],
  ['single_loss_tolerance', '单次亏损容忍'], ['volatility_tolerance', '波动容忍'], ['investment_horizon', '投资期限'],
  ['goal_type', '投资目标'], ['target_return', '目标收益'], ['target_period', '目标周期'], ['priority', '优先级'],
  ['capital_usage', '资金用途'], ['trading_style', '交易风格'],
] as const

export function UserProfileForm({ userId, profile, options, complete }: Props) {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()
  useEffect(() => { form.setFieldsValue(profile) }, [form, profile])
  const mutation = useMutation({
    mutationFn: async (values: Record<string, unknown>) => paperTradingApi.updateProfile({
      ...createWriteMeta('paper-profile'), user_id: userId, profile: values, confirmed: true,
    }),
    onSuccess: async () => {
      message.success('用户画像已由服务端保存')
      await queryClient.invalidateQueries({ queryKey: queryKeys.paperTrading(userId) })
      await queryClient.invalidateQueries({ queryKey: queryKeys.paperProfile(userId) })
    },
    onError: (error) => message.error(String(error)),
  })
  const submit = async () => {
    let values: Record<string, unknown>
    try {
      values = await form.validateFields()
    } catch {
      // Ant Design rejects validateFields when required inputs are missing.
      // Treat that as normal form feedback instead of an uncaught browser error.
      return
    }
    Modal.confirm({
      title: '确认更新模拟盘用户画像？',
      content: '画像会影响后续用户适配、风险约束和模拟盘组合。保存以服务端状态为准。',
      okText: '确认保存', cancelText: '取消', okButtonProps: { danger: false },
      onOk: () => mutation.mutate(values),
    })
  }
  return <PaperSectionCard sectionKey="user-profile" title="用户画像与模拟资金" extra={<Tag color={complete ? 'success' : 'warning'}>{complete ? '已完整' : '待补充'}</Tag>}>
    <Form form={form} layout="vertical" preserve={false} initialValues={profile}>
      <Row gutter={16}>
        <Col xs={24} md={8}><Form.Item name="nickname" label="昵称"><Input /></Form.Item></Col>
        <Col xs={24} md={8}><Form.Item name="available_capital" label="可用模拟资金（元）" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
        {fields.map(([name, label]) => <Col xs={24} md={8} key={name}><Form.Item name={name} label={label} rules={['age_range','income_stability','risk_level','investment_horizon'].includes(name) ? [{ required: true }] : []}><Select allowClear options={(options[name] ?? []).map((value) => ({ value, label: value }))} /></Form.Item></Col>)}
        <Col xs={24} md={12}><Form.Item name="preferred_industries" label="偏好行业"><Select mode="multiple" options={(options.preferred_industries ?? []).map((value) => ({ value, label: value }))} /></Form.Item></Col>
        <Col xs={24} md={12}><Form.Item name="avoided_industries" label="规避行业"><Select mode="multiple" options={(options.avoided_industries ?? []).map((value) => ({ value, label: value }))} /></Form.Item></Col>
        <Col xs={24}><Form.Item name="allow_high_volatility" valuePropName="checked"><Checkbox>允许高波动标的</Checkbox></Form.Item></Col>
      </Row>
      <Space><Button type="primary" onClick={submit} loading={mutation.isPending}>保存画像</Button><Tag>需要二次确认</Tag></Space>
    </Form>
  </PaperSectionCard>
}
