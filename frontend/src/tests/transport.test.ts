import { describe, expect, it } from 'vitest'
import { decodeTransport, encodeTransport } from '../api/transport'

describe('transport contract', () => {
  it('decodes dataframe into browser-native records', () => {
    const decoded = decodeTransport<{ columns: string[]; records: Array<Record<string, unknown>> }>({
      __transport_type__: 'dataframe',
      columns: ['stock_code', 'score'],
      records: [{ stock_code: '600519', score: 0.82 }],
    })
    expect(decoded.columns).toEqual(['stock_code', 'score'])
    expect(decoded.records[0].stock_code).toBe('600519')
  })

  it('decodes object, tuple and date values without Python objects', () => {
    const decoded = decodeTransport({
      __transport_type__: 'object',
      class_name: 'Result',
      data: {
        pair: { __transport_type__: 'tuple', items: [1, 2] },
        date: { __transport_type__: 'date', value: '2026-07-25' },
      },
    }) as { pair: number[]; date: string }
    expect(decoded).toEqual({ pair: [1, 2], date: '2026-07-25' })
  })

  it('encodes Date and Set explicitly', () => {
    expect(encodeTransport(new Date('2026-07-25T00:00:00.000Z'))).toEqual({ __transport_type__: 'datetime', value: '2026-07-25T00:00:00.000Z' })
    expect(encodeTransport(new Set(['a', 'b']))).toEqual({ __transport_type__: 'set', items: ['a', 'b'] })
  })
})
