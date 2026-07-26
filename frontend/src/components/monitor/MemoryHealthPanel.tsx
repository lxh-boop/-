import { ServiceHealthPanel } from './ServiceHealthPanel'; export function MemoryHealthPanel({ data }: { data?: Record<string, unknown> }) { return <ServiceHealthPanel title="Memory" data={data}/> }
