export interface PublicSettings {
  universe: string
  model_backend: string
  model_version: string
  default_topk: number
  current_user_id: string
  feature_flags: Record<string, boolean>
  credentials: { tushare_configured: boolean; llm_configured: boolean }
  llm: { mode: string; provider: string; model: string; endpoint_configured: boolean; profile_id: string }
  scheduler: { enabled: boolean; hour: number; minute: number }
  read_only: true
}
