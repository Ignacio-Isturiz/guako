import { settings } from '@/features/app/data/store.js'
import { esc } from '@/features/app/utils/html.js'

// Explicaciones en el idioma elegido en Ajustes: español, inglés o mezcla
export function explain(obj) {
  if (!obj) return ''
  const mode = settings().explain
  if (mode === 'en') return esc(obj.en)
  if (mode === 'mix') return `${esc(obj.es)} <span class="mix">${esc(obj.en)}</span>`
  return esc(obj.es)
}

// Traducción de lo que dice Guako: solo se muestra en español (con "Inglés" no hace falta)
export function gloss(obj) {
  if (!obj || settings().explain === 'en') return ''
  return esc(obj.es)
}
