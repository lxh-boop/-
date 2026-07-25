import { App as AntApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { BrowserRouter } from 'react-router-dom'
import { ErrorBoundary } from './components/common/ErrorBoundary'
import { useRecoveredTask } from './hooks/useRecoveredTask'
import { useTaskEvents } from './hooks/useTaskEvents'
import { AppLayout } from './layouts/AppLayout'
import { AppRoutes } from './routes/router'

function RuntimeBridge() {
  useRecoveredTask()
  useTaskEvents()
  return null
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{ algorithm: theme.defaultAlgorithm, token: { colorPrimary: '#0284c7', borderRadius: 10 } }}>
      <AntApp>
        <BrowserRouter>
          <RuntimeBridge />
          <ErrorBoundary>
            <AppLayout><AppRoutes /></AppLayout>
          </ErrorBoundary>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}
