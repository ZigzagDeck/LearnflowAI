import { useCallback, useEffect, useRef, useState } from 'react'
import {
  isExpectedSpeechInterruption,
  joinVoiceTranscript,
  pickPreferredInterviewVoice,
  speechRecognitionErrorMessage,
} from './interview-voice'

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
  loadSpeech?: (text: string, signal: AbortSignal) => Promise<Blob | null>
}

export function useInterviewVoice({ value, onChange, language = 'en-IN', loadSpeech }: UseInterviewVoiceOptions) {
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const audioUrlRef = useRef('')
  const speechRequestRef = useRef<AbortController | null>(null)
  const speechAttemptRef = useRef(0)
  const intentionallyStoppedUtterancesRef = useRef(new WeakSet<SpeechSynthesisUtterance>())
  const availableVoicesRef = useRef<SpeechSynthesisVoice[]>([])
  const baseTranscriptRef = useRef('')
  const onChangeRef = useRef(onChange)
  const [listening, setListening] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [preparingSpeech, setPreparingSpeech] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [error, setError] = useState('')

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  const recognitionSupported = typeof window !== 'undefined'
    && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)
  const browserSpeechSupported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const speechSupported = Boolean(loadSpeech) || browserSpeechSupported

  useEffect(() => {
    if (!browserSpeechSupported) return
    const refreshVoices = () => {
      availableVoicesRef.current = window.speechSynthesis.getVoices()
    }
    refreshVoices()
    window.speechSynthesis.addEventListener('voiceschanged', refreshVoices)
    return () => window.speechSynthesis.removeEventListener('voiceschanged', refreshVoices)
  }, [browserSpeechSupported])

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
    speechAttemptRef.current += 1
    speechRequestRef.current?.abort()
    speechRequestRef.current = null
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.removeAttribute('src')
      audioRef.current.load()
      audioRef.current = null
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current)
      audioUrlRef.current = ''
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      if (utteranceRef.current) {
        intentionallyStoppedUtterancesRef.current.add(utteranceRef.current)
        utteranceRef.current = null
      }
      window.speechSynthesis.cancel()
    }
    setPreparingSpeech(false)
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

  const speakWithBrowser = useCallback((text: string) => {
    if (!browserSpeechSupported || !text.trim()) {
      setError('The interviewer question could not be played. You can continue by reading it.')
      return
    }
    const utterance = new SpeechSynthesisUtterance(text)
    utteranceRef.current = utterance
    const preferredVoice = pickPreferredInterviewVoice(
      availableVoicesRef.current.length > 0
        ? availableVoicesRef.current
        : window.speechSynthesis.getVoices(),
      language,
    )
    if (preferredVoice) utterance.voice = preferredVoice
    utterance.lang = preferredVoice?.lang || language
    utterance.rate = 1.06
    utterance.pitch = 1
    utterance.onstart = () => {
      if (utteranceRef.current === utterance) setSpeaking(true)
    }
    utterance.onend = () => {
      if (utteranceRef.current === utterance) utteranceRef.current = null
      setSpeaking(false)
    }
    utterance.onerror = (event) => {
      const wasStoppedIntentionally = intentionallyStoppedUtterancesRef.current.has(utterance)
      intentionallyStoppedUtterancesRef.current.delete(utterance)
      if (utteranceRef.current === utterance) utteranceRef.current = null
      setSpeaking(false)
      if (wasStoppedIntentionally || isExpectedSpeechInterruption(event.error)) return
      setError('The interviewer question could not be played. You can continue by reading it.')
    }
    window.speechSynthesis.speak(utterance)
  }, [browserSpeechSupported, language])

  const speak = useCallback((text: string) => {
    const cleanText = text.trim()
    if (!speechSupported || !cleanText) return
    cancelListening()
    stopSpeaking()
    setError('')
    const attempt = speechAttemptRef.current
    if (!loadSpeech) {
      speakWithBrowser(cleanText)
      return
    }

    const request = new AbortController()
    speechRequestRef.current = request
    setPreparingSpeech(true)
    void loadSpeech(cleanText, request.signal).then(async (audioBlob) => {
      if (request.signal.aborted || attempt !== speechAttemptRef.current) return
      speechRequestRef.current = null
      setPreparingSpeech(false)
      if (!audioBlob) {
        speakWithBrowser(cleanText)
        return
      }
      const audioUrl = URL.createObjectURL(audioBlob)
      const audio = new Audio(audioUrl)
      audioUrlRef.current = audioUrl
      audioRef.current = audio
      audio.onplay = () => {
        if (audioRef.current === audio) setSpeaking(true)
      }
      const finish = () => {
        if (audioRef.current === audio) audioRef.current = null
        if (audioUrlRef.current === audioUrl) {
          URL.revokeObjectURL(audioUrl)
          audioUrlRef.current = ''
        }
        setSpeaking(false)
      }
      audio.onended = finish
      audio.onerror = () => {
        finish()
        if (attempt === speechAttemptRef.current) speakWithBrowser(cleanText)
      }
      try {
        await audio.play()
      } catch {
        finish()
        if (attempt === speechAttemptRef.current) speakWithBrowser(cleanText)
      }
    }).catch(() => {
      if (request.signal.aborted || attempt !== speechAttemptRef.current) return
      speechRequestRef.current = null
      setPreparingSpeech(false)
      speakWithBrowser(cleanText)
    })
  }, [cancelListening, loadSpeech, speakWithBrowser, speechSupported, stopSpeaking])

  useEffect(() => {
    if (!listening) return
    const timer = window.setInterval(() => setElapsedSeconds((current) => current + 1), 1_000)
    return () => window.clearInterval(timer)
  }, [listening])

  useEffect(() => () => {
    recognitionRef.current?.abort()
    speechRequestRef.current?.abort()
    audioRef.current?.pause()
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
  }, [])

  return {
    recognitionSupported,
    speechSupported,
    listening,
    speaking,
    preparingSpeech,
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
