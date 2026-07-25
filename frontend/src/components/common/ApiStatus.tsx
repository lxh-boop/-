import { Badge, Space, Typography } from 'antd'
import type { HealthData } from '../../types/api'

export function ApiStatus({ health }: { health?: HealthData }) {
  const connected = health?.status === 'ok'
  return (
    <Space size="small" data-testid="api-status">
      <Badge status={connected ? 'success' : 'processing'} />
      <Typography.Text strong>{connected ? 'FastAPI 已连接' : '正在连接 FastAPI'}</Typography.Text>
      {health ? <Typography.Text type="secondary">v{health.version} · {health.deployment_mode}</Typography.Text> : null}
    </Space>
  )
}
