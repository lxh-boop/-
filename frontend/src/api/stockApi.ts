import { getWeb } from './webApi'
import type { StockDetail, StockEvidence, StockExplanation, StockHistory } from '../types/stocks'
export const stockApi = {
  detail: (stockCode: string) => getWeb<StockDetail>(`/api/v1/web/stocks/${encodeURIComponent(stockCode)}`),
  history: (stockCode: string, limit = 120) => getWeb<StockHistory>(`/api/v1/web/stocks/${encodeURIComponent(stockCode)}/history`, { params: { limit } }),
  evidence: (stockCode: string, query = '', topK = 10) => getWeb<StockEvidence>(`/api/v1/web/stocks/${encodeURIComponent(stockCode)}/evidence`, { params: { query, top_k: topK } }),
  explanation: (stockCode: string) => getWeb<StockExplanation>(`/api/v1/web/stocks/${encodeURIComponent(stockCode)}/explanation`),
}
