import { getWeb } from './webApi'
import type { TablePayload } from '../types/common'
import type { ModelMetricsData, ModelSearchResults } from '../types/models'
export const modelApi = {
  metrics: () => getWeb<ModelMetricsData>('/api/v1/web/models/metrics'),
  catalog: () => getWeb<TablePayload>('/api/v1/web/models/catalog'),
  searchResults: () => getWeb<ModelSearchResults>('/api/v1/web/models/search-results'),
}
