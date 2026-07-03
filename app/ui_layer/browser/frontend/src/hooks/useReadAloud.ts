import { useCallback, useEffect, useState } from 'react'
import { stripMarkdown } from '../utils/stripMarkdown'
import { detectLanguage } from '../utils/detectLanguage'
import { inferVoiceGender, type VoiceGender } from '../utils/voiceGender'

/**
 * Read-aloud (text-to-speech) support built on the browser's Web Speech API.
 *
 * A single module-level controller owns the one global `speechSynthesis`
 * queue so that starting playback on one message automatically stops any
 * other, and every message's button can reflect the shared "who is speaking"
 * state. It also owns the user's voice/speed preferences (persisted to
 * localStorage, since the available voices are device-specific) and picks a
 * voice that matches the language of each message.
 *
 * Components read the speaking state via {@link useReadAloud}; the settings
 * screen manages preferences via {@link useTtsSettings}.
 */

const VOICE_KEY = 'craftbot-tts-voice' // stored voiceURI; '' = automatic
const RATE_KEY = 'craftbot-tts-rate' // stored speaking rate (0.5–2)
const GENDER_KEY = 'craftbot-tts-gender' // '' = any, or 'male' | 'female'

export type VoiceGenderPref = '' | VoiceGender

type Listener = (activeId: string | null) => void
type VoicesListener = (voices: SpeechSynthesisVoice[]) => void

function clampRate(rate: number): number {
  if (!Number.isFinite(rate)) return 1
  return Math.min(2, Math.max(0.5, rate))
}

class ReadAloudController {
  private activeId: string | null = null
  private readonly listeners = new Set<Listener>()
  private readonly voiceListeners = new Set<VoicesListener>()
  private voices: SpeechSynthesisVoice[] = []
  private keepAlive: ReturnType<typeof setInterval> | null = null
  readonly isSupported =
    typeof window !== 'undefined' && 'speechSynthesis' in window

  constructor() {
    if (!this.isSupported) return
    this.refreshVoices()
    // Voices populate asynchronously in most browsers.
    window.speechSynthesis.addEventListener?.('voiceschanged', () =>
      this.refreshVoices(),
    )
  }

  // ─── Voice inventory ────────────────────────────────────────────────

  private refreshVoices(): void {
    this.voices = window.speechSynthesis.getVoices() ?? []
    for (const fn of this.voiceListeners) fn(this.voices)
  }

  getVoices(): SpeechSynthesisVoice[] {
    return this.voices
  }

  subscribeVoices(fn: VoicesListener): () => void {
    this.voiceListeners.add(fn)
    return () => {
      this.voiceListeners.delete(fn)
    }
  }

  // ─── Preferences (persisted, device-local) ──────────────────────────

  getSelectedVoiceURI(): string {
    if (typeof localStorage === 'undefined') return ''
    return localStorage.getItem(VOICE_KEY) ?? ''
  }

  setSelectedVoiceURI(uri: string): void {
    localStorage.setItem(VOICE_KEY, uri)
  }

  getRate(): number {
    if (typeof localStorage === 'undefined') return 1
    return clampRate(parseFloat(localStorage.getItem(RATE_KEY) ?? '1'))
  }

  setRate(rate: number): void {
    localStorage.setItem(RATE_KEY, String(clampRate(rate)))
  }

  getGender(): VoiceGenderPref {
    if (typeof localStorage === 'undefined') return ''
    const v = localStorage.getItem(GENDER_KEY)
    return v === 'male' || v === 'female' ? v : ''
  }

  setGender(gender: VoiceGenderPref): void {
    localStorage.setItem(GENDER_KEY, gender)
  }

  /**
   * Choose the best voice for `text`:
   *  1. the user's explicitly selected voice when it fits the message's
   *     language (or the language is undetermined);
   *  2. otherwise a voice matching the detected language, honoring the
   *     preferred gender when possible, so non-Latin messages are read
   *     correctly and in the requested voice type.
   */
  private pickVoice(text: string): SpeechSynthesisVoice | null {
    const detected = detectLanguage(text)
    const selectedURI = this.getSelectedVoiceURI()
    const selected = selectedURI
      ? this.voices.find(v => v.voiceURI === selectedURI) ?? null
      : null

    if (selected) {
      const fits =
        !detected || selected.lang?.toLowerCase().startsWith(detected.toLowerCase())
      if (fits) return selected
    }

    const gender = this.getGender()

    // Language to auto-pick for: the detected script, or — when a gender is
    // requested but the script is undetermined (e.g. Latin) — the browser's
    // UI language, so the gender preference can still be honored.
    const uiLang =
      typeof navigator !== 'undefined'
        ? navigator.language?.split('-')[0]?.toLowerCase()
        : undefined
    const tag = detected?.toLowerCase() ?? (gender ? uiLang : undefined)
    if (!tag) return selected

    let candidates = this.voices.filter(v =>
      v.lang?.toLowerCase().startsWith(tag),
    )
    // If nothing matches the language but a gender is requested, widen the
    // pool to all voices so the gender preference still applies.
    if (candidates.length === 0 && gender) candidates = this.voices.slice()

    if (gender) {
      const gendered = candidates.filter(v => inferVoiceGender(v) === gender)
      if (gendered.length > 0) candidates = gendered
    }

    if (candidates.length > 0) {
      return candidates.find(v => v.default) ?? candidates[0]
    }

    return selected
  }

  private makeUtterance(text: string): SpeechSynthesisUtterance | null {
    const spoken = stripMarkdown(text)
    if (!spoken) return null

    const utterance = new SpeechSynthesisUtterance(spoken)
    const voice = this.pickVoice(text)
    if (voice) {
      utterance.voice = voice
      utterance.lang = voice.lang
    } else {
      const detected = detectLanguage(text)
      if (detected) utterance.lang = detected
    }
    utterance.rate = this.getRate()
    return utterance
  }

  // ─── Playback ───────────────────────────────────────────────────────

  // Chromium silently pauses speech synthesis after ~15s of continuous
  // playback. Nudging pause()/resume() on an interval keeps long messages
  // (which chat replies often are) playing to the end.
  private startKeepAlive(): void {
    this.stopKeepAlive()
    this.keepAlive = setInterval(() => {
      if (!window.speechSynthesis.speaking) {
        this.stopKeepAlive()
        return
      }
      window.speechSynthesis.pause()
      window.speechSynthesis.resume()
    }, 10000)
  }

  private stopKeepAlive(): void {
    if (this.keepAlive !== null) {
      clearInterval(this.keepAlive)
      this.keepAlive = null
    }
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }

  getActiveId(): string | null {
    return this.activeId
  }

  private setActive(id: string | null): void {
    this.activeId = id
    for (const fn of this.listeners) fn(id)
  }

  stop(): void {
    if (!this.isSupported) return
    this.stopKeepAlive()
    window.speechSynthesis.cancel()
    this.setActive(null)
  }

  /** Start reading `text` for `id`, or stop if `id` is already speaking. */
  toggle(id: string, text: string): void {
    if (!this.isSupported) return

    if (this.activeId === id) {
      this.stop()
      return
    }

    // Reading a different message: pre-empt whatever is currently playing.
    window.speechSynthesis.cancel()

    const utterance = this.makeUtterance(text)
    if (!utterance) return

    // Guard against a stale utterance clearing a newer selection: only clear
    // when *this* id is still the active one.
    const clearIfActive = () => {
      this.stopKeepAlive()
      if (this.activeId === id) this.setActive(null)
    }
    utterance.onend = clearIfActive
    utterance.onerror = clearIfActive

    this.setActive(id)
    window.speechSynthesis.speak(utterance)
    this.startKeepAlive()
  }

  /** Speak a one-off sample with the current preferences (settings preview). */
  speakSample(text: string): void {
    if (!this.isSupported) return
    this.stopKeepAlive()
    window.speechSynthesis.cancel()
    this.setActive(null)
    const utterance = this.makeUtterance(text)
    if (!utterance) return
    utterance.onend = () => this.stopKeepAlive()
    utterance.onerror = () => this.stopKeepAlive()
    window.speechSynthesis.speak(utterance)
    this.startKeepAlive()
  }
}

const controller = new ReadAloudController()

export interface ReadAloud {
  /** Whether this message is the one currently being read aloud. */
  isSpeaking: boolean
  /** Whether the browser supports speech synthesis at all. */
  isSupported: boolean
  /** Start reading the given text aloud, or stop if already reading. */
  toggle: (text: string) => void
}

export function useReadAloud(id: string): ReadAloud {
  const [activeId, setActiveId] = useState<string | null>(() =>
    controller.getActiveId(),
  )

  useEffect(() => controller.subscribe(setActiveId), [])

  const toggle = useCallback((text: string) => controller.toggle(id, text), [id])

  return {
    isSpeaking: activeId === id,
    isSupported: controller.isSupported,
    toggle,
  }
}

export interface TtsSettings {
  isSupported: boolean
  voices: SpeechSynthesisVoice[]
  selectedVoiceURI: string
  setSelectedVoiceURI: (uri: string) => void
  gender: VoiceGenderPref
  setGender: (gender: VoiceGenderPref) => void
  rate: number
  setRate: (rate: number) => void
  speakSample: (text: string) => void
  stop: () => void
}

/** Preferences + preview controls for the settings screen. */
export function useTtsSettings(): TtsSettings {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() =>
    controller.getVoices(),
  )
  const [selectedVoiceURI, setSelectedURIState] = useState<string>(() =>
    controller.getSelectedVoiceURI(),
  )
  const [gender, setGenderState] = useState<VoiceGenderPref>(() =>
    controller.getGender(),
  )
  const [rate, setRateState] = useState<number>(() => controller.getRate())

  useEffect(() => controller.subscribeVoices(setVoices), [])

  const setSelectedVoiceURI = useCallback((uri: string) => {
    controller.setSelectedVoiceURI(uri)
    setSelectedURIState(uri)
  }, [])

  const setGender = useCallback((g: VoiceGenderPref) => {
    controller.setGender(g)
    setGenderState(g)
  }, [])

  const setRate = useCallback((r: number) => {
    controller.setRate(r)
    setRateState(controller.getRate())
  }, [])

  const speakSample = useCallback(
    (text: string) => controller.speakSample(text),
    [],
  )

  const stop = useCallback(() => controller.stop(), [])

  return {
    isSupported: controller.isSupported,
    voices,
    selectedVoiceURI,
    setSelectedVoiceURI,
    gender,
    setGender,
    rate,
    setRate,
    speakSample,
    stop,
  }
}
