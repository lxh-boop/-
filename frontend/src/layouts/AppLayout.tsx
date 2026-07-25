import { useState, type ReactNode } from 'react'
import { Button, Layout, Menu, Space, Typography } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiStatus } from '../components/common/ApiStatus'
import { TaskDrawer } from '../components/tasks/TaskDrawer'
import { useApiHealth } from '../hooks/useApiHealth'
import { useAppStore } from '../stores/appStore'
import { useTaskStore } from '../stores/taskStore'

const { Header, Sider, Content } = Layout

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
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark">
        <div className="brand">{collapsed ? 'SA' : 'Stock Agent'}</div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          onClick={({ key }) => navigate(key)}
          items={[
            { key: '/', label: '连接与合同' },
            { key: '/runtime', label: '任务运行时' },
            { key: 'planned-dashboard', label: '业务页面迁移中', disabled: true },
          ]}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <Space size="large" wrap>
            <div>
              <Typography.Title level={4} style={{ margin: 0 }}>阶段 6 React 预览</Typography.Title>
              <Typography.Text type="secondary">公共合同冻结 · Streamlit 基线保留</Typography.Text>
            </div>
            <ApiStatus health={health.data} />
          </Space>
          <Button onClick={() => setTaskDrawerOpen(true)} data-testid="open-task-drawer">
            任务中心{task ? ` · ${task.status}` : ''}
          </Button>
        </Header>
        <Content className="app-content">{children}</Content>
      </Layout>
      <TaskDrawer open={taskDrawerOpen} onClose={() => setTaskDrawerOpen(false)} task={task} events={events} />
    </Layout>
  )
}
