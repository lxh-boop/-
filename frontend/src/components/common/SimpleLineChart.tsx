import { Empty } from 'antd'

interface Point { x: string; y: number }
export function SimpleLineChart({ points, height = 240, ariaLabel = '折线图' }: { points: Point[]; height?: number; ariaLabel?: string }) {
  const valid = points.filter((item) => Number.isFinite(item.y))
  if (valid.length < 2) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可绘制数据" />
  const width = 900
  const pad = 28
  const ys = valid.map((item) => item.y)
  const min = Math.min(...ys)
  const max = Math.max(...ys)
  const span = max - min || 1
  const coords = valid.map((item, index) => {
    const x = pad + (index / Math.max(valid.length - 1, 1)) * (width - pad * 2)
    const y = pad + (1 - (item.y - min) / span) * (height - pad * 2)
    return `${x},${y}`
  }).join(' ')
  return <div className="simple-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}><line x1={pad} y1={height-pad} x2={width-pad} y2={height-pad} className="chart-axis"/><line x1={pad} y1={pad} x2={pad} y2={height-pad} className="chart-axis"/><polyline points={coords} className="chart-line"/><text x={pad} y={18} className="chart-label">{max.toFixed(4)}</text><text x={pad} y={height-6} className="chart-label">{min.toFixed(4)}</text></svg><div className="chart-range"><span>{valid[0]?.x}</span><span>{valid.at(-1)?.x}</span></div></div>
}
