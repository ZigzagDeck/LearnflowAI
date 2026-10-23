import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ReactMarkdown from 'react-markdown'
import { markdownOptions, normalizeMathDelimiters } from '../src/markdown.ts'

function render(content) {
  return renderToStaticMarkup(createElement(ReactMarkdown, markdownOptions, normalizeMathDelimiters(content)))
}

test('renders dollar and TeX math delimiters with accessible MathML', () => {
  for (const content of [String.raw`$\alpha + \frac{1}{2}$`, String.raw`\(\alpha + \frac{1}{2}\)`]) {
    const html = render(content)
    assert.match(html, /class="katex"/)
    assert.match(html, /<math /)
    assert.match(html, /<mfrac>/)
  }
  for (const content of [String.raw`\[\sum_{i=1}^n i\]`, '$$\nx^2\n$$']) {
    assert.match(render(content), /class="katex-display"/)
  }
})

test('preserves fenced and inline code, including unfinished fences', () => {
  for (const content of [
    String.raw`Use \`\(x\)\` literally.`.replaceAll('\\`', '`'),
    '```python\n' + String.raw`print("\(x\)")` + '\n```',
    '~~~text\n' + String.raw`\[x\]` + '\n~~~',
    '```text\n' + String.raw`\(unfinished\)`,
  ]) {
    assert.equal(normalizeMathDelimiters(content), content)
    assert.doesNotMatch(render(content), /class="katex"/)
  }
})

test('retains ordinary Markdown, currencies, and escaped delimiters', () => {
  const html = render('**Bold**\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\nCosts $5 and $10.')
  assert.match(html, /<strong>Bold<\/strong>/)
  assert.match(html, /<table>/)
  assert.match(html, /Costs \$5 and \$10\./)
  assert.equal(normalizeMathDelimiters(String.raw`\\(literal\\)`), String.raw`\\(literal\\)`)
})

test('malformed math stays readable and untrusted commands cannot inject HTML', () => {
  assert.doesNotThrow(() => render(String.raw`$\frac{$`))
  assert.match(render(String.raw`$\frac{$`), /katex-error/)
  assert.doesNotMatch(render(String.raw`$\href{javascript:alert(1)}{click}$`), /href="javascript:/)
  assert.doesNotMatch(render('<script>alert(1)</script>'), /<script>/)
})
