export interface AgentSession {
  conversation_id: string
  user_id: string
  title: string
  status: string
  language: string
  created_at: string
  updated_at: string
  last_message_at: string
  last_run_id: string
}

export interface AgentSessionPage {
  records: AgentSession[]
  total: number
  offset: number
  limit: number
}

export interface AgentMessage {
  message_id: string
  conversation_id: string
  user_id: string
  role: 'user' | 'assistant' | 'system' | string
  content: string
  language: string
  created_at: string
  run_id: string
  task_id: string
  result_summary: Record<string, unknown>
}

export interface AgentMessagePage {
  records: AgentMessage[]
  total: number
  offset: number
  limit: number
}

export interface AgentRunDetail {
  run: Record<string, unknown>
  steps: Array<Record<string, unknown>>
  tool_calls: Array<Record<string, unknown>>
  sources: Array<Record<string, unknown>>
  proposals: Array<Record<string, unknown>>
  counts: {
    steps: number
    tool_calls: number
    sources: number
    proposals: number
  }
}

export interface AgentPendingAction {
  plan_id: string
  run_id: string
  intent: string
  operation_type: string
  confirmation_status: string
  execution_status: string
  created_at: string
  expires_at: string
  before_state_summary: unknown
  proposed_changes: unknown
  after_state_preview: unknown
  warnings: unknown
  validation_results: unknown
  confirmation_phrase: string
}

export interface AgentPendingActionPage {
  records: AgentPendingAction[]
  total: number
}

export interface AgentStrategyProposal {
  available: boolean
  proposal: Record<string, unknown> | null
  versions: Array<Record<string, unknown>>
}

export interface AgentDiagnostics {
  run?: Record<string, unknown>
  trace?: Record<string, unknown>
  messages?: Array<Record<string, unknown>>
  message_count?: number
  reflection_available?: boolean
  handoff_available?: boolean
  summary?: Record<string, unknown> | string
  observations?: Array<Record<string, unknown>>
  [key: string]: unknown
}
