import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { Button, Card, Space } from 'antd'
import type { CardProps } from 'antd'

const DEFAULT_COLLAPSED: Record<string, boolean> = {
  'account-summary': false,
  'task-actions': false,
  'user-profile': false,
  'asset-curve': true,
  'paper-records': false,
  'risk-diagnostics': true,
  'cash-flow': true,
  'backfill': true,
  'proposals': false,
}

interface PaperSectionContextValue {
  collapsed: Record<string, boolean>
  isCollapsed: (sectionKey: string) => boolean
  toggle: (sectionKey: string) => void
  setAll: (value: boolean) => void
}

const PaperSectionContext = createContext<PaperSectionContextValue | null>(null)

export function PaperSectionProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(DEFAULT_COLLAPSED)
  const value = useMemo<PaperSectionContextValue>(() => ({
    collapsed,
    isCollapsed: (sectionKey) => Boolean(collapsed[sectionKey]),
    toggle: (sectionKey) => setCollapsed((current) => ({
      ...current,
      [sectionKey]: !current[sectionKey],
    })),
    setAll: (next) => setCollapsed((current) => Object.fromEntries(
      Object.keys(current).map((key) => [key, next]),
    )),
  }), [collapsed])

  return <PaperSectionContext.Provider value={value}>{children}</PaperSectionContext.Provider>
}

function usePaperSections(): PaperSectionContextValue {
  const value = useContext(PaperSectionContext)
  if (!value) throw new Error('PaperSectionCard must be used inside PaperSectionProvider')
  return value
}

interface PaperSectionCardProps extends Omit<CardProps, 'title' | 'extra' | 'styles' | 'children'> {
  sectionKey: string
  title: ReactNode
  extra?: ReactNode
  children: ReactNode
}

export function PaperSectionCard({ sectionKey, title, extra, children, ...cardProps }: PaperSectionCardProps) {
  const sections = usePaperSections()
  const collapsed = sections.isCollapsed(sectionKey)
  return (
    <Card
      {...cardProps}
      className={`paper-section-card ${collapsed ? 'paper-section-card--collapsed' : ''} ${cardProps.className ?? ''}`.trim()}
      title={title}
      extra={(
        <Space size="small" wrap>
          {extra}
          <Button
            type="text"
            size="small"
            aria-expanded={!collapsed}
            aria-controls={`paper-section-${sectionKey}`}
            onClick={() => sections.toggle(sectionKey)}
          >
            {collapsed ? '展开' : '收起'}
          </Button>
        </Space>
      )}
      styles={{ body: { display: collapsed ? 'none' : undefined } }}
    >
      <div id={`paper-section-${sectionKey}`}>{children}</div>
    </Card>
  )
}

export function PaperSectionControls() {
  const sections = usePaperSections()
  return (
    <Space wrap className="paper-section-controls">
      <Button size="small" onClick={() => sections.setAll(false)}>全部展开</Button>
      <Button size="small" onClick={() => sections.setAll(true)}>全部收起</Button>
    </Space>
  )
}
