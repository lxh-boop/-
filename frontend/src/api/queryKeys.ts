export const queryKeys = {
  health: ['health'] as const,
  task: (taskId: string) => ['task', taskId] as const,
}
