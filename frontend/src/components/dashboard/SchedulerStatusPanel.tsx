import { Card, Descriptions, Tag } from 'antd'
import type { PublicSettings } from '../../types/settings'
export function SchedulerStatusPanel({ settings }: { settings: PublicSettings }) { const s=settings.scheduler; return <Card title="自动更新配置（只读）"><Descriptions column={1} size="small"><Descriptions.Item label="状态"><Tag color={s.enabled?'success':'default'}>{s.enabled?'已配置':'未启用'}</Tag></Descriptions.Item><Descriptions.Item label="计划时间">{String(s.hour).padStart(2,'0')}:{String(s.minute).padStart(2,'0')}</Descriptions.Item></Descriptions></Card> }
