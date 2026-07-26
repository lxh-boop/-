import { Navigate, Route, Routes } from 'react-router-dom'
import { HealthPage } from '../pages/HealthPage'
import { RuntimePage } from '../pages/RuntimePage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { RankingPage } from '../pages/dashboard/RankingPage'
import { StockDetailPage } from '../pages/dashboard/StockDetailPage'
import { ModelMetricsPage } from '../pages/dashboard/ModelMetricsPage'
import { ModelSearchPage } from '../pages/dashboard/ModelSearchPage'
import { BacktestPage } from '../pages/dashboard/BacktestPage'
import { NewsPage } from '../pages/dashboard/NewsPage'
import { SettingsPage } from '../pages/dashboard/SettingsPage'
import { SystemMonitorPage } from '../pages/monitor/SystemMonitorPage'

export function AppRoutes() {
  return <Routes>
    <Route path="/" element={<Navigate to="/dashboard" replace />} />
    <Route path="/dashboard" element={<RankingPage />} />
    <Route path="/stocks" element={<StockDetailPage />} />
    <Route path="/stocks/:stockCode" element={<StockDetailPage />} />
    <Route path="/models/metrics" element={<ModelMetricsPage />} />
    <Route path="/models/search" element={<ModelSearchPage />} />
    <Route path="/backtests" element={<BacktestPage />} />
    <Route path="/news" element={<NewsPage />} />
    <Route path="/settings" element={<SettingsPage />} />
    <Route path="/monitor" element={<SystemMonitorPage />} />
    <Route path="/platform" element={<HealthPage />} />
    <Route path="/runtime" element={<RuntimePage />} />
    <Route path="/health" element={<Navigate to="/platform" replace />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes>
}
