export type InterviewInputMode = 'text' | 'voice'

type InterviewVoiceOption = {
  lang: string
  name: string
  localService?: boolean
}

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

export function interviewVoicePreferenceScore(
  voice: InterviewVoiceOption,
  targetLanguage = 'en-IN',
): number {
  const name = voice.name.toLowerCase()
  const language = voice.lang.toLowerCase()
  const target = targetLanguage.toLowerCase()
  const targetBase = target.split('-')[0]
  let score = 0

  if (language === target) score += 100
  else if (language.startsWith(`${targetBase}-`) || language === targetBase) score += 45
  if (name.includes('natural')) score += 80
  if (name.includes('online')) score += 28
  if (name.includes('microsoft')) score += 18
  if (name.includes('google')) score += 14
  if (voice.localService === false) score += 8
  if (name.includes('espeak') || name.includes('compact')) score -= 50
  return score
}

export function pickPreferredInterviewVoice<T extends InterviewVoiceOption>(
  voices: T[],
  targetLanguage = 'en-IN',
): T | undefined {
  return [...voices].sort(
    (left, right) => interviewVoicePreferenceScore(right, targetLanguage)
      - interviewVoicePreferenceScore(left, targetLanguage),
  )[0]
}
