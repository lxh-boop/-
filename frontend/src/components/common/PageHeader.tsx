import { Space, Typography } from 'antd'
export function PageHeader({ title, description }: { title: string; description: string }) {
  return <Space direction="vertical" size={2} className="page-heading"><Typography.Title level={2}>{title}</Typography.Title><Typography.Text type="secondary">{description}</Typography.Text></Space>
}
