import assert from 'node:assert/strict'
import test from 'node:test'
import {
  formatVoiceElapsed,
  interviewVoicePreferenceScore,
  isExpectedSpeechInterruption,
  joinVoiceTranscript,
  pickPreferredInterviewVoice,
  speechRecognitionErrorMessage,
} from '../src/interview-voice.ts'

test('voice transcript keeps an existing answer while appending clean recognition text', () => {
  assert.equal(
    joinVoiceTranscript('Existing answer.  ', '  Final sentence.', '  partial thought  '),
    'Existing answer. Final sentence. partial thought',
  )
  assert.equal(joinVoiceTranscript('', undefined, '  new answer  '), 'new answer')
})

test('voice timer is stable for fresh, minute-long, and invalid negative durations', () => {
  assert.equal(formatVoiceElapsed(0), '00:00')
  assert.equal(formatVoiceElapsed(67.9), '01:07')
  assert.equal(formatVoiceElapsed(-12), '00:00')
})

test('microphone failures give actionable text-mode fallbacks', () => {
  assert.match(speechRecognitionErrorMessage('not-allowed'), /Allow microphone access/)
  assert.match(speechRecognitionErrorMessage('audio-capture'), /No microphone was found/)
  assert.match(speechRecognitionErrorMessage('no-speech'), /No speech was detected/)
  assert.match(speechRecognitionErrorMessage('network'), /continue in text mode/)
  assert.match(speechRecognitionErrorMessage('unknown'), /continue in text mode/)
})

test('stopping question audio does not surface a false playback failure', () => {
  assert.equal(isExpectedSpeechInterruption('canceled'), true)
  assert.equal(isExpectedSpeechInterruption('interrupted'), true)
  assert.equal(isExpectedSpeechInterruption('audio-busy'), false)
  assert.equal(isExpectedSpeechInterruption(), false)
})

test('interviewer audio prefers a natural regional English voice', () => {
  const voices = [
    { name: 'Basic English', lang: 'en-US', localService: true },
    { name: 'Microsoft Neerja Online (Natural)', lang: 'en-IN', localService: false },
    { name: 'Microsoft David', lang: 'en-US', localService: true },
  ]
  assert.equal(pickPreferredInterviewVoice(voices, 'en-IN')?.name, voices[1].name)
  assert.ok(
    interviewVoicePreferenceScore(voices[1], 'en-IN')
      > interviewVoicePreferenceScore(voices[0], 'en-IN'),
  )
})
