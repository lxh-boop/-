import { useEffect, useState } from 'react'
import { Button, Card, Input, Space, Tag, Typography } from 'antd'
import type { OwnerMode } from '../../stores/sessionIdentity'

interface UserContextSelectorProps {
  activeUserId: string
  systemUserId: string
  ownerMode: OwnerMode
  onSelectUser: (userId: string) => void
  onUseSystemUser: () => void
}

export function UserContextSelector({
  activeUserId,
  systemUserId,
  ownerMode,
  onSelectUser,
  onUseSystemUser,
}: UserContextSelectorProps) {
  const [draftUserId, setDraftUserId] = useState(activeUserId)

  useEffect(() => {
    setDraftUserId(activeUserId)
  }, [activeUserId])

  const submit = () => {
    const next = draftUserId.trim()
    if (next) onSelectUser(next)
  }

  return (
    <Card size="small" title="当前模拟盘用户" data-testid="paper-user-context">
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Space wrap>
          <Typography.Text strong>{activeUserId}</Typography.Text>
          <Tag color={ownerMode === 'system' ? 'success' : 'processing'}>
            {ownerMode === 'system' ? '跟随系统设置' : '手动选择'}
          </Tag>
          <Typography.Text type="secondary">系统当前用户：{systemUserId}</Typography.Text>
        </Space>
        <Space.Compact style={{ width: '100%', maxWidth: 620 }}>
          <Input
            aria-label="模拟盘用户 ID"
            value={draftUserId}
            onChange={(event) => setDraftUserId(event.target.value)}
            onPressEnter={submit}
            placeholder="输入已有模拟盘用户 ID"
          />
          <Button onClick={submit}>切换用户</Button>
          <Button onClick={onUseSystemUser} disabled={ownerMode === 'system' && activeUserId === systemUserId}>
            使用系统当前用户
          </Button>
        </Space.Compact>
        <Typography.Text type="secondary">
          账户、持仓和画像均按用户 ID 隔离。旧版验收账号 refactor_test 不再作为业务默认用户。
        </Typography.Text>
      </Space>
    </Card>
  )
}
