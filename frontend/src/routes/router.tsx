import { Navigate, Route, Routes } from 'react-router-dom'
import { HealthPage } from '../pages/HealthPage'
import { RuntimePage } from '../pages/RuntimePage'
import { NotFoundPage } from '../pages/NotFoundPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<HealthPage />} />
      <Route path="/runtime" element={<RuntimePage />} />
      <Route path="/health" element={<Navigate to="/" replace />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
