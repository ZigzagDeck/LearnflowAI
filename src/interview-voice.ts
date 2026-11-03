export type InterviewInputMode = 'text' | 'voice'

export function joinVoiceTranscript(...parts: Array<string | undefined>): string {
  return parts
    .map((part) => part?.trim() || '')
    .filter(Boolean)
    .join(' ')
}

export function formatVoiceElapsed(totalSeconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds))
  const minutes = Math.floor(safeSeconds / 60)
  const seconds = safeSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export function speechRecognitionErrorMessage(code: string): string {
  if (code === 'not-allowed' || code === 'service-not-allowed') {
    return 'Microphone access is blocked. Allow microphone access or continue in text mode.'
  }
  if (code === 'audio-capture') {
    return 'No microphone was found. Connect a microphone or continue in text mode.'
  }
  if (code === 'no-speech') {
    return 'No speech was detected. Try again or type your answer.'
  }
  if (code === 'network') {
    return 'Voice recognition could not connect. Try again or continue in text mode.'
  }
  return 'Voice recognition stopped unexpectedly. Try again or continue in text mode.'
}

export function isExpectedSpeechInterruption(code?: string): boolean {
  return code === 'canceled' || code === 'interrupted'
}
