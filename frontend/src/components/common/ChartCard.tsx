import type { ReactNode } from 'react'
import { Card } from 'antd'
export function ChartCard({ title, children }: { title: string; children: ReactNode }) { return <Card title={title}>{children}</Card> }
