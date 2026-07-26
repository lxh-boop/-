import { Empty, Typography } from 'antd'

export function EmptyState({ title, description }: { title?: string; description: string }) {
  return <Empty description={<div>{title && <Typography.Text strong>{title}</Typography.Text>}{title && <br/>}<Typography.Text type="secondary">{description}</Typography.Text></div>} />
}
