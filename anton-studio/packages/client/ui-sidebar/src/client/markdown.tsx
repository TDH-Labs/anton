import type { ReactNode } from 'react'

/**
 * Minimal, dependency-free markdown renderer: paragraphs, `- ` bullet
 * lists, `**bold**`, `*italic*`, and `` `code` ``. Covers the note bodies
 * this package renders (README §7 Memory — "Render the markdown; do not
 * dump raw text into a monospace column") without pulling in a markdown
 * library for one small, known-shape surface.
 */
export function renderMarkdown(source: string): ReactNode {
  const blocks = source.trim().split(/\n{2,}/)
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split('\n').map(l => l.trim()).filter(l => l !== '')
        const isList = lines.length > 0 && lines.every(l => l.startsWith('- '))
        if (isList) {
          return (
            <ul key={i} style={{ margin: '0 0 12px', paddingLeft: 18 }}>
              {lines.map((l, j) => <li key={j} style={{ marginBottom: 4 }}>{renderInline(l.slice(2))}</li>)}
            </ul>
          )
        }
        return <p key={i} style={{ margin: '0 0 12px' }}>{renderInline(lines.join(' '))}</p>
      })}
    </>
  )
}

function renderInline(text: string): ReactNode {
  const nodes: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g
  let lastIndex = 0
  let key = 0
  for (const match of text.matchAll(pattern)) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index))
    const token = match[0]
    if (token.startsWith('**')) nodes.push(<strong key={key++}>{token.slice(2, -2)}</strong>)
    else if (token.startsWith('`')) nodes.push(<code key={key++} style={{ fontFamily: 'ui-monospace, Menlo, monospace', fontSize: '0.92em' }}>{token.slice(1, -1)}</code>)
    else nodes.push(<em key={key++}>{token.slice(1, -1)}</em>)
    lastIndex = match.index + token.length
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex))
  return nodes
}
