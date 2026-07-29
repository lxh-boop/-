import { Button, Card, Input, Space } from 'antd'
import { useState } from 'react'
export function EvidenceSearchPanel({ loading, onSearch }: { loading?: boolean; onSearch: (query: string) => void }) { const [query,setQuery]=useState(''); return <Card title="证据检索（只读）"><Space.Compact style={{width:'100%'}}><Input value={query} onChange={(e)=>setQuery(e.target.value)} onPressEnter={()=>onSearch(query)} placeholder="输入要查找的新闻、公告或风险"/><Button type="primary" loading={loading} onClick={()=>onSearch(query)}>检索</Button></Space.Compact></Card> }
