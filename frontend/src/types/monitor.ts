import type { TablePayload } from './common'
export interface MonitorSummary { snapshot: Record<string, unknown>; alerts: Record<string, unknown>[] }
export type MonitorServices = Record<string, Record<string, unknown>>
export type MonitorTable = TablePayload<Record<string, unknown>>
