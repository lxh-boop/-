const TYPE_KEY = '__transport_type__'

export interface TransportDataFrame {
  columns: string[]
  records: Array<Record<string, unknown>>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function decodeTransport<T = unknown>(value: unknown): T {
  if (Array.isArray(value)) {
    return value.map((item) => decodeTransport(item)) as T
  }
  if (!isRecord(value)) {
    return value as T
  }

  const valueType = value[TYPE_KEY]
  switch (valueType) {
    case 'dataframe':
      return {
        columns: Array.isArray(value.columns) ? value.columns.map(String) : [],
        records: decodeTransport(value.records ?? []),
      } as T
    case 'series':
      return decodeTransport(value.data ?? {}) as T
    case 'path':
    case 'datetime':
    case 'date':
    case 'time':
      return String(value.value ?? '') as T
    case 'enum':
      return decodeTransport(value.value) as T
    case 'tuple':
    case 'set':
      return decodeTransport(value.items ?? []) as T
    case 'object':
      return decodeTransport(value.data ?? {}) as T
    default:
      return Object.fromEntries(
        Object.entries(value).map(([key, item]) => [key, decodeTransport(item)]),
      ) as T
  }
}

export function encodeTransport(value: unknown): unknown {
  if (value === null || value === undefined) return value ?? null
  if (value instanceof Date) {
    return { [TYPE_KEY]: 'datetime', value: value.toISOString() }
  }
  if (value instanceof Set) {
    return { [TYPE_KEY]: 'set', items: [...value].map(encodeTransport) }
  }
  if (Array.isArray(value)) return value.map(encodeTransport)
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, encodeTransport(item)]),
    )
  }
  return value
}
