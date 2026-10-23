import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import type { Options } from 'react-markdown'

export const markdownOptions: Pick<Options, 'remarkPlugins' | 'rehypePlugins'> = {
  remarkPlugins: [remarkGfm, remarkMath],
  rehypePlugins: [[rehypeKatex, { trust: false, strict: 'ignore', maxSize: 20, maxExpand: 1000 }]],
}

/** Accept the TeX delimiters models commonly use, without rewriting code samples. */
export function normalizeMathDelimiters(markdown: string): string {
  let result = ''
  let index = 0
  const tokens = /[`~\\$]/g
  while (index < markdown.length) {
    tokens.lastIndex = index
    const token = tokens.exec(markdown)
    if (!token) return result + markdown.slice(index)
    result += markdown.slice(index, token.index)
    index = token.index
    const rest = markdown.slice(index)
    const linePrefix = markdown.slice(markdown.lastIndexOf('\n', index - 1) + 1, index)
    const fence = /^ {0,3}$/.test(linePrefix) && /^(?:`{3,}|~{3,})/.exec(rest)
    if (fence) {
      const marker = fence[0]
      const openingEnd = markdown.indexOf('\n', index)
      const closing = new RegExp(`^ {0,3}${marker[0]}{${marker.length},}[ \\t]*$`, 'gm')
      closing.lastIndex = openingEnd < 0 ? markdown.length : openingEnd + 1
      const match = closing.exec(markdown)
      const end = match ? match.index + match[0].length : markdown.length
      result += markdown.slice(index, end)
      index = end
      continue
    }
    const ticks = /^`+/.exec(rest)
    if (ticks) {
      const closing = new RegExp(`(?<!\x60)\x60{${ticks[0].length}}(?!\x60)`, 'g')
      closing.lastIndex = index + ticks[0].length
      const match = closing.exec(markdown)
      if (match) {
        const end = match.index + match[0].length
        result += markdown.slice(index, end)
        index = end
        continue
      }
    }
    if (rest.startsWith('\\(') || rest.startsWith('\\[')) {
      const display = rest[1] === '['
      const closing = display ? '\\]' : '\\)'
      const end = markdown.indexOf(closing, index + 2)
      if (end >= 0) {
        const formula = markdown.slice(index + 2, end).trim()
        result += display ? `\n$$\n${formula}\n$$\n` : `$${formula}$`
        index = end + 2
        continue
      }
    }
    // A pair of prices is prose, even though Markdown math sees paired dollars.
    const prices = /^\$(\d[\d,.]*\s+(?:and|or|to|each|per|for|versus|vs\.?)[^$\n]*)\$(?=\d)/.exec(rest)
    if (prices) {
      result += `\\$${prices[1]}\\$`
      index += prices[0].length
      continue
    }
    // Preserve escaped delimiters (including a literal double backslash).
    if (rest[0] === '\\' && rest.length > 1) {
      result += rest.slice(0, 2)
      index += 2
    } else {
      result += rest[0]
      index += 1
    }
  }
  return result
}
