import { Flex, Spin, Typography } from 'antd'

export function PageLoading({ message = '正在加载' }: { message?: string }) {
  return <Flex vertical align="center" gap={12} className="page-loading"><Spin /><Typography.Text type="secondary">{message}</Typography.Text></Flex>
}
