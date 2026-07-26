import { describe, expect, it } from 'vitest'
import { createWriteMeta } from '../api/writeOperationApi'
import { migrateOwnerIdentity, resolveOwnerId } from '../stores/sessionIdentity'

describe('stage 6.3 protected write metadata', () => {
  it('creates non-empty request and idempotency identifiers', () => {
    const first = createWriteMeta('profile')
    const second = createWriteMeta('profile')
    expect(first.request_id).toContain('req-profile-')
    expect(first.idempotency_key).toContain('idem-profile-')
    expect(first.request_id).not.toBe(second.request_id)
    expect(first.idempotency_key).not.toBe(second.idempotency_key)
  })
})

describe('stage 6.3 paper user identity', () => {
  it('migrates the legacy refactor test account back to system-user mode', () => {
    expect(migrateOwnerIdentity('refactor_test')).toEqual({ ownerId: 'default', ownerMode: 'system' })
  })

  it('uses the configured system user unless the user explicitly switches accounts', () => {
    expect(resolveOwnerId('default', 'system', 'real_user')).toBe('real_user')
    expect(resolveOwnerId('manual_user', 'manual', 'real_user')).toBe('manual_user')
  })
})
