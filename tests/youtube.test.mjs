import assert from 'node:assert/strict'
import test from 'node:test'
import { youtubeEmbedUrl } from '../src/youtube.ts'

test('opens watch, short, and embed citations at the cited second', () => {
  for (const url of ['https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'https://youtu.be/dQw4w9WgXcQ', 'https://m.youtube.com/shorts/dQw4w9WgXcQ', 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ']) {
    assert.equal(youtubeEmbedUrl(url, 12.9), 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?start=12&autoplay=1')
  }
})

test('invalid or hostile citation URLs cannot crash rendering or create a preview', () => {
  for (const url of [null, 'not a URL', 'javascript:alert(1)', 'https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ', 'https://youtube.com/watch?v=invalid']) {
    assert.equal(youtubeEmbedUrl(url), null)
  }
  assert.match(youtubeEmbedUrl('https://youtu.be/dQw4w9WgXcQ', Infinity), /start=0&/)
})
