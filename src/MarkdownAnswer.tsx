import ReactMarkdown from 'react-markdown'
import { markdownOptions, normalizeMathDelimiters } from './markdown'
import 'katex/dist/katex.min.css'

export default function MarkdownAnswer({ children }: { children: string }) {
  return (
    <div className="markdown-answer">
      <ReactMarkdown
        {...markdownOptions}
        components={{
          a: ({ children: label, ...props }) => <a {...props} target="_blank" rel="noreferrer">{label}</a>,
        }}
      >{normalizeMathDelimiters(children)}</ReactMarkdown>
    </div>
  )
}
