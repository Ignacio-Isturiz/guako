// Voz de Guako con la síntesis de voz del navegador (si existe). Respeta el ajuste "sonido".
import { settings } from '@/features/app/data/store.js'

const synth = 'speechSynthesis' in window ? window.speechSynthesis : null
export const canSpeak = !!synth

let voices = []
if (synth) {
  const load = () => (voices = synth.getVoices())
  load()
  synth.addEventListener?.('voiceschanged', load)
}
const englishVoice = () =>
  voices.find((v) => /^en[-_]US/i.test(v.lang) && /female|zira|samantha|aria|jenny/i.test(v.name)) ||
  voices.find((v) => /^en[-_]US/i.test(v.lang)) ||
  voices.find((v) => /^en/i.test(v.lang))

// Duración estimada de una frase (para animar cuando no hay voz disponible)
export const estimate = (text) => Math.max(1400, text.split(/\s+/).length * 380 + 600)

export function stopSpeaking() {
  synth?.cancel()
}

// Dice `text` en inglés. Siempre se resuelve (con voz o con un tiempo estimado).
export function speak(text, { rate = 1, force = false } = {}) {
  return new Promise((resolve) => {
    const on = force || settings().sound
    if (!synth || !on) return setTimeout(resolve, on ? 0 : estimate(text) * 0.6)
    synth.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'en-US'
    u.rate = rate
    const v = englishVoice()
    if (v) u.voice = v
    let done = false
    const end = () => {
      if (!done) {
        done = true
        resolve()
      }
    }
    u.onend = end
    u.onerror = end
    setTimeout(end, estimate(text) / rate + 1500) // por si el navegador nunca avisa
    synth.speak(u)
  })
}
