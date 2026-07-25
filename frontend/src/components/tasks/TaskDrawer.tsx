import { Drawer, List, Typography } from 'antd'
import type { TaskEvent, TaskRecord } from '../../types/task'
import { TaskProgress } from './TaskProgress'

export function TaskDrawer({ open, onClose, task, events }: { open: boolean; onClose: () => void; task: TaskRecord | null; events: TaskEvent[] }) {
  return (
    <Drawer title="任务运行详情" open={open} onClose={onClose} width={520}>
      {task ? <TaskProgress task={task} /> : <Typography.Text type="secondary">暂无任务</Typography.Text>}
      <List
        style={{ marginTop: 20 }}
        size="small"
        header={<Typography.Text strong>SSE 事件</Typography.Text>}
        dataSource={[...events].reverse()}
        locale={{ emptyText: '尚未收到事件' }}
        renderItem={(event) => (
          <List.Item>
            <List.Item.Meta
              title={`${event.sequence} · ${event.event_type}`}
              description={String(event.data.message ?? event.created_at)}
            />
          </List.Item>
        )}
      />
    </Drawer>
  )
}
