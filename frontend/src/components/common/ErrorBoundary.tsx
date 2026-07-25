import type { ErrorInfo, ReactNode } from 'react'
import { Component } from 'react'
import { Alert } from 'antd'

interface Props { children: ReactNode }
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State { return { error } }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('React page error', error, info)
  }

  render() {
    if (this.state.error) {
      return <Alert type="error" showIcon message="页面渲染失败" description={this.state.error.message} />
    }
    return this.props.children
  }
}
