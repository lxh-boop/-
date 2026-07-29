import { Card, Statistic, Tag } from 'antd'
import { MetricGrid } from '../common/MetricGrid'
import type { DashboardSummary } from '../../types/dashboard'
export function ModelStatusCards({ summary }: { summary: DashboardSummary }) {
  return <MetricGrid><Card><Statistic title="排名记录" value={summary.ranking.total}/><Tag color={summary.ranking.available?'success':'default'}>{summary.ranking.available?'可用':'缺失'}</Tag></Card><Card><Statistic title="模型后端" value={summary.model.backend || '未配置'}/><div>{summary.model.version || 'latest'}</div></Card><Card><Statistic title="新闻事件" value={summary.news.total}/><Tag color={summary.news.available?'success':'default'}>{summary.news.available?'有缓存':'无缓存'}</Tag></Card><Card><Statistic title="回测结果" value={summary.backtest.available?'可用':'暂无'}/></Card></MetricGrid>
}
