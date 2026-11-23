// Historial real de conversaciones (GET /api/sessions) con la forma que usan Inicio y Progreso.
// Solo existen dos puntajes (gramática y fluidez); los demás aspectos aún no se miden.
import { TOPICS } from '@/features/app/data/seed.js'
import { listSessions } from '@/features/app/data/sessions-api.js'
import en from '@/features/app/i18n/en.js'

export const LIVE_ASPECTS = ['gram', 'fluency']

const DEFAULT_ART = 'vida-diaria'

// Los temas se guardan con su nombre en inglés ("Travel"); así se reconoce su ilustración
export const artOf = (topic) => TOPICS.find((tp) => en.topics[tp.id].name === topic)?.art ?? DEFAULT_ART

export const minutesOf = (seconds) => Math.max(1, Math.round(seconds / 60))

// Sesión del backend → conversación con la forma del almacén de demo.
// `scores` solo trae lo que existe; `overall` es el promedio de esos puntajes (null si no hay ninguno).
export function toConversation(s) {
  const scores = {}
  if (s.grammar_score != null) scores.gram = s.grammar_score
  if (s.fluency_score != null) scores.fluency = s.fluency_score
  const values = Object.values(scores)
  return {
    id: String(s.id),
    date: s.created_at,
    topicId: 'custom',
    topicLabel: s.topic,
    role: s.role,
    level: s.level,
    durationMin: minutesOf(s.duration_seconds),
    art: artOf(s.topic),
    ended: !!s.ended_at,
    scores,
    overall: values.length ? Math.round(values.reduce((a, b) => a + b, 0) / values.length) : null,
  }
}

// La más reciente primero (el backend ya las ordena así)
export async function loadHistory() {
  return (await listSessions()).map(toConversation)
}
