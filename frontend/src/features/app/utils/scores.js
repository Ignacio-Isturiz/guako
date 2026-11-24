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
// Pronunciación: Azure puntúa alto a quien se hace entender (la mediana real es 94), así que sus
// etiquetas son más exigentes para no dar una impresión demasiado optimista.
const BANDS = { pron: [92, 80] }
export const tone = (v, aspect) => {
  const [high, mid] = BANDS[aspect] || [80, 65]
  return v >= high ? 'high' : v >= mid ? 'mid' : 'low'
}
export const toneText = (v, aspect) => t(`app.score.${tone(v, aspect)}`)
