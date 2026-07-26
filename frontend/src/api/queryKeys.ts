export const queryKeys = {
  health: ['health'] as const,
  task: (taskId: string) => ['task', taskId] as const,
  dashboard: ['web', 'dashboard'] as const,
  rankings: ['web', 'dashboard', 'rankings'] as const,
  stock: (stockCode: string) => ['web', 'stock', stockCode] as const,
  models: ['web', 'models'] as const,
  backtest: (backtestId = 'latest') => ['web', 'backtest', backtestId] as const,
  news: ['web', 'news'] as const,
  settings: ['web', 'settings'] as const,
  monitor: ['web', 'monitor'] as const,
}
