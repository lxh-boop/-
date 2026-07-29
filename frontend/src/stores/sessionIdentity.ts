export type OwnerMode = 'system' | 'manual'

export const SYSTEM_OWNER_FALLBACK = 'default'
export const LEGACY_TEST_OWNER_ID = 'refactor_test'

export function normalizeOwnerId(value: unknown, fallback = SYSTEM_OWNER_FALLBACK): string {
  const text = String(value ?? '').trim()
  return text || fallback
}

export function resolveOwnerId(ownerId: unknown, ownerMode: OwnerMode, systemOwnerId: unknown): string {
  if (ownerMode === 'system') {
    return normalizeOwnerId(systemOwnerId)
  }
  return normalizeOwnerId(ownerId)
}

export function migrateOwnerIdentity(value: unknown): { ownerId: string; ownerMode: OwnerMode } {
  const ownerId = normalizeOwnerId(value)
  if (ownerId === LEGACY_TEST_OWNER_ID) {
    return { ownerId: SYSTEM_OWNER_FALLBACK, ownerMode: 'system' }
  }
  return { ownerId, ownerMode: 'manual' }
}
