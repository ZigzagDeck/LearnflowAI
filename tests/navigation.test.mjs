import assert from 'node:assert/strict'
import test from 'node:test'
import { publicPageForHash, accountActionToken } from '../src/navigation.ts'

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

test('account action links work for signed-out and signed-in routing', () => {
  for (const action of ['forgot-password', 'reset-password', 'verify-email']) {
    assert.equal(publicPageForHash(`#${action}?token=sample`), action)
  }
  assert.equal(accountActionToken('#reset-password?token=sample'), 'sample')
  assert.equal(accountActionToken('#reset-password'), '')
  assert.equal(accountActionToken('#verify-email?token=a%2Bb'), 'a+b')
})
