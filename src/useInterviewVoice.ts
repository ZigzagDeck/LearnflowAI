import { useCallback, useEffect, useRef, useState } from 'react'
import { joinVoiceTranscript, speechRecognitionErrorMessage } from './interview-voice'

type SpeechRecognitionAlternativeLike = { transcript: string }
type SpeechRecognitionResultLike = {
  isFinal: boolean
  length: number
  [index: number]: SpeechRecognitionAlternativeLike
}
type SpeechRecognitionEventLike = Event & {
  results: {
    length: number
    [index: number]: SpeechRecognitionResultLike
  }
}
type SpeechRecognitionErrorEventLike = Event & { error: string }

type SpeechRecognitionLike = {
  continuous: boolean
  interimResults: boolean
  lang: string
  maxAlternatives: number
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
}

type UseInterviewVoiceOptions = {
  value: string
  onChange: (value: string) => void
  language?: string
}

export function useInterviewVoice({ value, onChange, language = 'en-IN' }: UseInterviewVoiceOptions) {
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const baseTranscriptRef = useRef('')
  const onChangeRef = useRef(onChange)
  const [listening, setListening] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [error, setError] = useState('')

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  const recognitionSupported = typeof window !== 'undefined'
    && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)
  const speechSupported = typeof window !== 'undefined' && 'speechSynthesis' in window

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  const cancelListening = useCallback(() => {
    recognitionRef.current?.abort()
    recognitionRef.current = null
    setListening(false)
    setElapsedSeconds(0)
  }, [])

  const stopSpeaking = useCallback(() => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
    setSpeaking(false)
  }, [])

  const startListening = useCallback(() => {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!Recognition) {
      setError('Voice input is not supported in this browser. Continue in text mode or use Chrome or Edge.')
      return
    }

    stopSpeaking()
    recognitionRef.current?.abort()
    const recognition = new Recognition()
    recognitionRef.current = recognition
    baseTranscriptRef.current = value.trim()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = language
    recognition.maxAlternatives = 1

    recognition.onresult = (event) => {
      const finalParts: string[] = []
      const interimParts: string[] = []
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index]
        const transcript = result?.[0]?.transcript?.trim()
        if (!transcript) continue
        if (result.isFinal) finalParts.push(transcript)
        else interimParts.push(transcript)
      }
      onChangeRef.current(joinVoiceTranscript(
        baseTranscriptRef.current,
        finalParts.join(' '),
        interimParts.join(' '),
      ))
    }
    recognition.onerror = (event) => {
      setError(speechRecognitionErrorMessage(event.error))
      setListening(false)
    }
    recognition.onend = () => {
      if (recognitionRef.current === recognition) recognitionRef.current = null
      setListening(false)
    }

    setError('')
    setElapsedSeconds(0)
    setListening(true)
    try {
      recognition.start()
    } catch {
      recognitionRef.current = null
      setListening(false)
      setError('Voice recognition is already active. Stop it before trying again.')
    }
  }, [language, stopSpeaking, value])

  const speak = useCallback((text: string) => {
    if (!speechSupported || !text.trim()) return
    cancelListening()
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = language
    utterance.rate = 0.96
    utterance.onstart = () => setSpeaking(true)
    utterance.onend = () => setSpeaking(false)
    utterance.onerror = () => {
      setSpeaking(false)
      setError('The interviewer question could not be played. You can continue by reading it.')
    }
    window.speechSynthesis.speak(utterance)
  }, [cancelListening, language, speechSupported])

  useEffect(() => {
    if (!listening) return
    const timer = window.setInterval(() => setElapsedSeconds((current) => current + 1), 1_000)
    return () => window.clearInterval(timer)
  }, [listening])

  useEffect(() => () => {
    recognitionRef.current?.abort()
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
  }, [])

  return {
    recognitionSupported,
    speechSupported,
    listening,
    speaking,
    elapsedSeconds,
    error,
    startListening,
    stopListening,
    cancelListening,
    speak,
    stopSpeaking,
    clearError: () => setError(''),
  }
}
