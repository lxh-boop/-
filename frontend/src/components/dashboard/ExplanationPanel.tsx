import { Alert, Card, Typography } from 'antd'
import type { StockExplanation } from '../../types/stocks'
export function ExplanationPanel({ explanation }: { explanation?: StockExplanation }) { return <Card title="已有 AI 解释缓存">{explanation?.available?<Typography.Paragraph style={{whiteSpace:'pre-wrap'}}>{typeof explanation.cached==='string'?explanation.cached:JSON.stringify(explanation.cached,null,2)}</Typography.Paragraph>:<Alert type="info" showIcon message="暂无解释缓存" description={explanation?.message ?? '阶段 6.2 不触发新的 LLM 调用。'}/>}</Card> }
