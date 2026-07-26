import { Alert } from 'antd'
export function ReadOnlyNotice() { return <Alert type="info" showIcon message="阶段 6.2 只读迁移" description="本页面只查询并展示已有业务结果，不修改设置、不启动回测、不保存监控快照，也不写入模拟盘。" /> }
