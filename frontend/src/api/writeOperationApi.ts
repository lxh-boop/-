import type { WriteRequestMeta } from '../types/paperTrading'

function randomId(prefix: string): string {
  const value = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${value}`
}

export function createWriteMeta(operation: string): WriteRequestMeta {
  return {
    request_id: randomId(`req-${operation}`),
    idempotency_key: randomId(`idem-${operation}`),
  }
}
