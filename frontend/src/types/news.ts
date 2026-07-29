import type { TablePayload } from './common'
export interface NewsEventRecord { event_id?: string; date?: string; code?: string; name?: string; title?: string; source?: string; url?: string; publish_time?: string; [key: string]: unknown }
export type NewsEventsData = TablePayload<NewsEventRecord>
