import assert from 'node:assert/strict'
import test from 'node:test'
import { materialErrorMessage, materialStatusLabel } from '../src/material-feedback.ts'

test('locked, empty, and unreadable files suggest a useful next action', () => {
  assert.match(materialErrorMessage('PDF is empty or password protected.'), /empty or password-protected/)
  assert.match(materialErrorMessage('Uploaded file is empty.'), /empty/)
  assert.match(materialErrorMessage('PDF is corrupt.'), /save a new copy/)
  assert.match(materialErrorMessage('No readable text was found after OCR.'), /clearer scan/)
})

test('provider setup and quota errors are distinguished from a bad file', () => {
  assert.match(materialErrorMessage('GOOGLE_CLOUD_PROJECT is not configured.'), /app needs attention/)
  assert.match(materialErrorMessage('The configured monthly Jina embedding limit has been reached.'), /app has reached its usage limit/)
  assert.match(materialErrorMessage('Google OCR credentials returned no access token.'), /app owner/)
})

test('unknown failures do not expose internal provider details', () => {
  for (const detail of ['Unexpected SQLite exception at D:/private/file', { detail: 'raw error' }, null]) {
    const message = materialErrorMessage(detail)
    assert.match(message, /could not get this material ready/)
    assert.doesNotMatch(message, /SQLite|private|raw error/)
  }
})

test('connection, login, and video problems stay actionable', () => {
  assert.match(materialErrorMessage('Failed to fetch'), /internet connection/)
  assert.match(materialErrorMessage('Your session has expired. Sign in again.'), /sign in again/)
  assert.match(materialErrorMessage('No transcript or captions are available.'), /video is public and has captions/)
})

test('material labels reflect actual states without claiming readiness early', () => {
  assert.equal(materialStatusLabel('uploaded'), 'Waiting to get ready')
  assert.equal(materialStatusLabel('processing'), 'Getting ready')
  assert.equal(materialStatusLabel('ready'), 'Ready to use')
  assert.equal(materialStatusLabel('failed'), 'Needs attention')
  assert.equal(materialStatusLabel('unknown'), 'Checking status')
})
