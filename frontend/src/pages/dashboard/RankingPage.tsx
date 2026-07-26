import { useQuery } from '@tanstack/react-query'
import { Card, Col, Row, Space, Table, Tag } from 'antd'
import { useNavigate } from 'react-router-dom'
import { dashboardApi } from '../../api/dashboardApi'
import { ModelStatusCards } from '../../components/dashboard/ModelStatusCards'
import { ProbabilityChart } from '../../components/dashboard/ProbabilityChart'
import { RankingScoreChart } from '../../components/dashboard/RankingScoreChart'
import { RankingTable } from '../../components/dashboard/RankingTable'
import { EmptyState } from '../../components/common/EmptyState'
import { PageHeader } from '../../components/common/PageHeader'
import { PageLoading } from '../../components/common/PageLoading'
import { ReadOnlyNotice } from '../../components/common/ReadOnlyNotice'

export function RankingPage() {
  const navigate = useNavigate()
  const summary = useQuery({ queryKey: ['web','dashboard','summary'], queryFn: dashboardApi.summary })
  const rankings = useQuery({ queryKey: ['web','dashboard','rankings'], queryFn: () => dashboardApi.rankings(0, 300) })
  const freshness = useQuery({ queryKey: ['web','dashboard','freshness'], queryFn: dashboardApi.dataFreshness })
  if (summary.isLoading || rankings.isLoading) return <PageLoading />
  if (summary.error || rankings.error) return <EmptyState title="只读首页加载失败" description={String(summary.error ?? rankings.error)} />
  const records = rankings.data?.records ?? []
  return <Space direction="vertical" size="large" style={{width:'100%'}}>
    <PageHeader title="首页 / 预测排名" description="展示已有排名、模型状态、数据新鲜度和只读图表。" />
    <ReadOnlyNotice />
    {summary.data && <ModelStatusCards summary={summary.data}/>} 
    <Card title={`最新预测排名 · ${rankings.data?.total ?? 0} 条`}><RankingTable records={records} onSelect={(code)=>navigate(`/stocks/${code}`)}/></Card>
    <Row gutter={[16,16]}><Col xs={24} xl={12}><RankingScoreChart records={records}/></Col><Col xs={24} xl={12}><ProbabilityChart records={records}/></Col></Row>
    <Card title="数据新鲜度"><Table size="small" pagination={false} rowKey="key" dataSource={freshness.data ?? []} columns={[{title:'数据项',dataIndex:'label'},{title:'状态',dataIndex:'status',render:(v:string)=><Tag color={v==='ready'?'success':'default'}>{v==='ready'?'已就绪':'缺失'}</Tag>},{title:'更新时间',dataIndex:'updated_at',render:(v:string|null)=>v?new Date(v).toLocaleString():'—'},{title:'大小',dataIndex:'size_bytes',render:(v:number|null)=>v?`${(v/1024).toFixed(1)} KB`:'—'}]}/></Card>
  </Space>
}
