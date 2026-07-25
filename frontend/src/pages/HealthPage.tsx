import { Alert, Card, Col, Descriptions, Row, Space, Statistic, Typography } from 'antd'
import { useApiHealth } from '../hooks/useApiHealth'
import { PageLoading } from '../components/common/PageLoading'
import { errorMessage } from '../api/errors'

export function HealthPage() {
  const health = useApiHealth()
  if (health.isPending) return <PageLoading message="正在验证 React → Nginx → FastAPI" />
  if (health.isError) return <Alert type="error" showIcon message="FastAPI 连接失败" description={errorMessage(health.error)} />

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Typography.Title level={2}>React 基础设施与公共合同</Typography.Title>
        <Typography.Paragraph type="secondary">
          当前 React 仅作为阶段 6.1 预览入口；正式 Streamlit 服务保持不变。后端并行重构必须继续兼容已冻结的 HTTP、Task 和 SSE 合同。
        </Typography.Paragraph>
      </div>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}><Card><Statistic title="API 状态" value="已连接" valueStyle={{ color: '#16a34a' }} /></Card></Col>
        <Col xs={24} md={8}><Card><Statistic title="API 版本" value={health.data.version} /></Card></Col>
        <Col xs={24} md={8}><Card><Statistic title="部署模式" value={health.data.deployment_mode} /></Card></Col>
      </Row>
      <Card title="健康检查响应" data-testid="health-card">
        <Descriptions bordered column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="service">{health.data.service}</Descriptions.Item>
          <Descriptions.Item label="status">{health.data.status}</Descriptions.Item>
          <Descriptions.Item label="version">{health.data.version}</Descriptions.Item>
          <Descriptions.Item label="deployment_mode">{health.data.deployment_mode}</Descriptions.Item>
        </Descriptions>
      </Card>
      <Alert
        type="info"
        showIcon
        message="并行重构边界"
        description="React 分支只新增 frontend、contracts/stage6 和 stage6 测试；Agent、Application Service、数据库、RAG 与 Task Runtime 继续由后端分支负责。"
      />
    </Space>
  )
}
