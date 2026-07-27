export interface CredentialStatus {
  tushare_configured: boolean
  llm_configured: boolean
}

export interface PublicLlmStatus {
  mode: 'api' | 'local' | string
  provider: string
  model: string
  endpoint_configured: boolean
  profile_id: string
}

export interface EditableSettingsConfiguration {
  llm_mode: 'api' | 'local'
  api: {
    provider: string
    base_url: string
    model: string
    configured: boolean
    custom_configured: boolean
    default_available: boolean
  }
  local: {
    provider: string
    base_url: string
    effective_base_url: string
    model: string
  }
  tushare: {
    configured: boolean
    custom_configured: boolean
    default_available: boolean
  }
}

export interface PublicSettings {
  universe: string
  model_backend: string
  model_version: string
  default_topk: number
  current_user_id: string
  feature_flags: Record<string, boolean>
  credentials: CredentialStatus
  llm: PublicLlmStatus
  configuration: EditableSettingsConfiguration
  scheduler: { enabled: boolean; hour: number; minute: number }
  read_only: boolean
}

export interface SettingsUpdateRequest {
  request_id: string
  idempotency_key: string
  confirmed: boolean
  llm_mode: 'api' | 'local'
  api_provider: string
  api_base_url: string
  api_model: string
  api_credential?: string
  clear_api_credential: boolean
  local_base_url: string
  local_model: string
  tushare_credential?: string
  clear_tushare_credential: boolean
}

export interface SettingsUpdateResult {
  request_id: string
  idempotency_key: string
  status: string
  settings: PublicSettings
}
