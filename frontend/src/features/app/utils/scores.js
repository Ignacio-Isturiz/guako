import { t } from '@/core/i18n.js'

// Los cinco aspectos que se evalúan, su color y el tono de cada puntaje
export const ASPECT_COLOR = {
  pron: '#e8201a',
  gram: '#0a7cff',
  fluency: '#f0a500',
  clarity: '#0b2a6b',
  listening: '#1aa05a',
}
export const aspectName = (a) => t(`app.aspects.${a}`)
export const tone = (v) => (v >= 80 ? 'high' : v >= 65 ? 'mid' : 'low')
export const toneText = (v) => t(`app.score.${tone(v)}`)
