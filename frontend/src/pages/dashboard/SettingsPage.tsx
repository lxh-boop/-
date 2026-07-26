import { useQuery } from '@tanstack/react-query'
import { Card, Col, Descriptions, Row, Space, Tag } from 'antd'
import { settingsApi } from '../../api/settingsApi'
import { SchedulerStatusPanel } from '../../components/dashboard/SchedulerStatusPanel'
import { EmptyState } from '../../components/common/EmptyState'
import { PageHeader } from '../../components/common/PageHeader'
import { PageLoading } from '../../components/common/PageLoading'
import { ReadOnlyNotice } from '../../components/common/ReadOnlyNotice'
import type { PublicSettings } from '../../types/settings'

const EMPTY_CREDENTIAL_STATUS = {
  tushare_configured: false,
  llm_configured: false,
}

const EMPTY_LLM_STATUS = {
  mode: '',
  provider: '',
  model: '',
  endpoint_configured: false,
  profile_id: '',
}

const EMPTY_SCHEDULER_STATUS = {
  enabled: false,
  hour: 0,
  minute: 0,
}

export function SettingsPage() {
  const query = useQuery({ queryKey: ['web', 'settings'], queryFn: settingsApi.get })

  if (query.isLoading) return <PageLoading />
  if (query.error || !query.data) {
    return <EmptyState title="设置读取失败" description={String(query.error ?? '无数据')} />
  }

  // Keep the read-only page renderable when an older API image returns a
  // partial public-settings DTO.  The backend fix restores the real boolean
  // configuration indicators; these defaults only prevent a blank page.
  const settings: PublicSettings = {
    ...query.data,
    feature_flags: query.data.feature_flags ?? {},
    credentials: query.data.credentials ?? EMPTY_CREDENTIAL_STATUS,
    llm: query.data.llm ?? EMPTY_LLM_STATUS,
    scheduler: query.data.scheduler ?? EMPTY_SCHEDULER_STATUS,
  }

  const credentials = settings.credentials
  const llm = settings.llm

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader
        title="系统设置"
        description="仅显示公开配置状态；密钥、密码、本地路径不会返回浏览器。"
      />
      <ReadOnlyNotice />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="业务配置">
            <Descriptions column={1}>
              <Descriptions.Item label="股票池">{settings.universe}</Descriptions.Item>
              <Descriptions.Item label="模型后端">{settings.model_backend}</Descriptions.Item>
              <Descriptions.Item label="模型版本">{settings.model_version}</Descriptions.Item>
              <Descriptions.Item label="默认 TopK">{settings.default_topk}</Descriptions.Item>
              <Descriptions.Item label="当前用户">{settings.current_user_id}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="能力状态">
            <Descriptions column={1}>
              {Object.entries(settings.feature_flags).map(([key, value]) => (
                <Descriptions.Item key={key} label={key}>
                  <Tag color={value ? 'success' : 'default'}>{value ? '开启' : '关闭'}</Tag>
                </Descriptions.Item>
              ))}
              <Descriptions.Item label="Tushare Token">
                <Tag color={credentials.tushare_configured ? 'success' : 'warning'}>
                  {credentials.tushare_configured ? '已配置' : '未配置'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="LLM">
                <Tag color={credentials.llm_configured ? 'success' : 'warning'}>
                  {credentials.llm_configured ? '已配置' : '未配置'}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="LLM 公开信息">
            <Descriptions column={1}>
              <Descriptions.Item label="模式">{llm.mode || '—'}</Descriptions.Item>
              <Descriptions.Item label="Provider">{llm.provider || '—'}</Descriptions.Item>
              <Descriptions.Item label="Model">{llm.model || '—'}</Descriptions.Item>
              <Descriptions.Item label="Endpoint">
                {llm.endpoint_configured ? '已配置' : '未配置'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <SchedulerStatusPanel settings={settings} />
        </Col>
      </Row>
    </Space>
  )
}
