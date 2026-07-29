import { Button, Input, Space, Typography } from 'antd'
import { useState } from 'react'

const QUICK_QUESTIONS = [
  '查看当前模拟盘账户和持仓',
  '查看当前预测排名前十的股票',
  '分析贵州茅台',
  '查看每日自动更新和调度状态',
]

export function ChatComposer({
  disabled,
  loading,
  onSubmit,
}: {
  disabled: boolean
  loading: boolean
  onSubmit: (value: string) => Promise<void> | void
}) {
  const [value, setValue] = useState('')

  const submit = async (question = value) => {
    const normalized = question.trim()
    if (!normalized || disabled || loading) return
    await onSubmit(normalized)
    setValue('')
  }

  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <Space wrap>
      <Typography.Text type="secondary">快捷提问：</Typography.Text>
      {QUICK_QUESTIONS.map((item) => <Button
        key={item}
        size="small"
        disabled={disabled || loading}
        onClick={() => void submit(item)}
      >{item}</Button>)}
    </Space>
    <Input.TextArea
      value={value}
      onChange={(event) => setValue(event.target.value)}
      autoSize={{ minRows: 3, maxRows: 8 }}
      maxLength={20_000}
      placeholder="请输入问题，例如：分析 600519，或查看当前模拟盘持仓"
      data-testid="agent-composer-input"
      disabled={disabled}
      onPressEnter={(event) => {
        if (!event.shiftKey) {
          event.preventDefault()
          void submit()
        }
      }}
    />
    <div className="agent-composer-actions">
      <Typography.Text type="secondary">Enter 发送，Shift + Enter 换行</Typography.Text>
      <Button
        type="primary"
        loading={loading}
        disabled={disabled || !value.trim()}
        onClick={() => void submit()}
      data-testid="agent-send-button"
      >发送</Button>
    </div>
  </Space>
}
