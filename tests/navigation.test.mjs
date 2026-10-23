import assert from 'node:assert/strict'
import test from 'node:test'
import { publicPageForHash } from '../src/navigation.ts'

test('new visitors and landing section links open the landing page', () => {
  for (const hash of ['', '#home', '#how-it-works', '#possibilities', '#make-it-yours', '#landing-main', '#unknown']) {
    assert.equal(publicPageForHash(hash), 'landing')
  }
})

test('sign-in and create-account links open the requested account form', () => {
  assert.equal(publicPageForHash('#login'), 'login')
  assert.equal(publicPageForHash('#register'), 'register')
})

test('every protected workspace deep link requires sign-in for a visitor', () => {
  for (const destination of ['materials', 'chat', 'summary', 'quiz', 'interview', 'history']) {
    assert.equal(publicPageForHash(`#${destination}`), 'login')
  }
})
