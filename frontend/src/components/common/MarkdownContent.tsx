import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function MarkdownContent({ content }: { content: string }) {
  return <div className="markdown-content">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
        table: ({ node: _node, ...props }) => <div className="markdown-table-wrap">
          <table {...props} />
        </div>,
      }}
    >
      {content}
    </ReactMarkdown>
  </div>
}
