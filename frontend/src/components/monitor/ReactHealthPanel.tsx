import { ServiceHealthPanel } from './ServiceHealthPanel'; export function ReactHealthPanel({ data }: { data?: Record<string, unknown> }) { return <ServiceHealthPanel title="ReAct" data={data}/> }
