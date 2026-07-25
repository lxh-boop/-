import { describe, expect, it } from 'vitest'
import { TERMINAL_TASK_STATUSES } from '../types/task'

describe('task status contract', () => {
  it('keeps all Stage 4 terminal states', () => {
    expect([...TERMINAL_TASK_STATUSES].sort()).toEqual(['cancelled', 'failed', 'interrupted', 'succeeded', 'timed_out'])
  })
})
