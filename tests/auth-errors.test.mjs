import assert from 'node:assert/strict'
import test from 'node:test'
import { authErrorMessage } from '../src/auth-errors.ts'

test('shows FastAPI password validation without exposing submitted input', () => {
  const message = authErrorMessage(422, {
    detail: [{ loc: ['body', 'password'], msg: 'String should have at least 8 characters', input: 'private submitted value' }],
  })
  assert.equal(message, 'Password: String should have at least 8 characters')
  assert.ok(!message.includes('private submitted value'))
})

test('does not mislabel name validation as a password failure', () => {
  assert.equal(authErrorMessage(422, {
    detail: [{ loc: ['body', 'display_name'], msg: 'String should have at least 2 characters' }],
  }), 'Display name: String should have at least 2 characters')
})

test('preserves backend string validation messages', () => {
  assert.equal(authErrorMessage(422, { detail: 'Password must include an uppercase letter and a number.' }),
    'Password must include an uppercase letter and a number.')
})

test('handles missing, malformed, and unexpected error details safely', () => {
  for (const payload of [null, {}, { detail: {} }, { detail: 42 }, { detail: [null, {}, { msg: 1 }] }]) {
    assert.equal(authErrorMessage(422, payload), 'Please check your email, password, and account details.')
  }
})

test('uses status-specific login, duplicate-account, and rate-limit messages', () => {
  assert.match(authErrorMessage(401, { detail: [] }), /Incorrect email or password/)
  assert.match(authErrorMessage(409, {}), /already exists/)
  assert.match(authErrorMessage(429, {}), /Too many attempts/)
  assert.match(authErrorMessage(503, {}), /Something went wrong/)
})
