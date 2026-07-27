import { useState, type ReactNode } from 'react'
import { Button, Layout, Menu, Space, Typography } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiStatus } from '../components/common/ApiStatus'
import { TaskDrawer } from '../components/tasks/TaskDrawer'
import { useApiHealth } from '../hooks/useApiHealth'
import { useAppStore } from '../stores/appStore'
import { useTaskStore } from '../stores/taskStore'

const { Header, Sider, Content } = Layout
const routeKey = (pathname: string) => pathname.startsWith('/stocks') ? '/stocks' : pathname

export function AppLayout({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const health = useApiHealth()
  const taskDrawerOpen = useAppStore((state) => state.taskDrawerOpen)
  const setTaskDrawerOpen = useAppStore((state) => state.setTaskDrawerOpen)
  const task = useTaskStore((state) => state.task)
  const events = useTaskStore((state) => state.events)

  return (
    <Layout className="app-shell">
      <Sider className="app-sider" collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark">
        <div className="brand">{collapsed ? 'SA' : 'Stock Agent'}</div>
        <div className="app-sider-menu-scroll">
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[routeKey(location.pathname)]}
            onClick={({ key }) => navigate(key)}
            items={[
              { key: '/dashboard', label: '首页 / 预测排名' },
              { key: '/stocks', label: '个股详情' },
              { key: 'model-group', label: '模型与回测', children: [
                { key: '/models/metrics', label: '模型指标' },
                { key: '/models/search', label: '模型搜索结果' },
                { key: '/backtests', label: '回测分析' },
              ] },
              { key: '/news', label: '新闻事件' },
              { key: '/paper-trading', label: 'AI 模拟盘' },
              { key: '/agent', label: 'AI Agent' },
              { key: '/settings', label: '系统设置' },
              { key: '/monitor', label: '系统监控' },
              { key: 'platform-group', label: '平台诊断', children: [
                { key: '/platform', label: '连接与合同' },
                { key: '/runtime', label: '任务运行时' },
              ] },
            ]}
          />
        </div>
      </Sider>
      <Layout className="app-main-layout">
        <Header className="app-header">
          <Space size="large" wrap>
            <div>
              <Typography.Title level={4} style={{ margin: 0 }}>阶段 6.4 React 预览</Typography.Title>
              <Typography.Text type="secondary">AI Agent、会话、Trace 与任务恢复 · Streamlit 对照基线保留</Typography.Text>
            </div>
            <ApiStatus health={health.data} />
          </Space>
          <Button onClick={() => setTaskDrawerOpen(true)} data-testid="open-task-drawer">
            任务中心{task ? ` · ${task.status}` : ''}
          </Button>
        </Header>
        <Content className="app-content-scroll" data-testid="app-content-scroll">
          <main className="app-content">{children}</main>
        </Content>
      </Layout>
      <TaskDrawer open={taskDrawerOpen} onClose={() => setTaskDrawerOpen(false)} task={task} events={events} />
    </Layout>
  )
}
