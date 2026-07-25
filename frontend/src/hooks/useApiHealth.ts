import { useQuery } from '@tanstack/react-query'
import { fetchHealth } from '../api/healthApi'
import { queryKeys } from '../api/queryKeys'

export function useApiHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: fetchHealth,
    refetchInterval: 15_000,
    retry: 2,
  })
}
