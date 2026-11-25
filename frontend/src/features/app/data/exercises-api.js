// Cliente de la práctica personalizada (ejercicios hechos con las reglas que fallaste).
//   GET  /api/practice/exercises?size=&rule=   → { exercises, focus }  (sin respuestas dentro)
//   POST /api/practice/check  { exercise_id, answer }   → { correct, expected, rule }
//   POST /api/practice/speak  (multipart: exercise_id + audio) → { correct, expected, rule, heard }
// No se guarda nada de las respuestas: es práctica, no una evaluación.
import { request } from '@/features/app/data/sessions-api.js'

const json = (res) => res.json()

export const getExercises = ({ size = 8, rule } = {}) => {
  const query = new URLSearchParams({ size: String(size), ...(rule ? { rule } : {}) })
  return request(`/api/practice/exercises?${query}`).then(json)
}

export const checkAnswer = (exerciseId, answer) =>
  request('/api/practice/check', { method: 'POST', json: { exercise_id: exerciseId, answer } }).then(json)

export function checkSpeech(exerciseId, blob, filename) {
  const form = new FormData()
  form.append('exercise_id', exerciseId)
  form.append('audio', blob, filename)
  return request('/api/practice/speak', { method: 'POST', body: form }).then(json)
}
