// Cliente de la API de conversaciones del backend (la sesión viaja en una cookie httpOnly).
//   POST  /api/sessions                              → crea la sesión { level, topic, role? }
//   GET   /api/sessions                              → mis conversaciones (historial)
//   POST  /api/sessions/{id}/opening                 → la primera frase de Guako en su papel
//   POST  /api/sessions/{id}/turns                   → un turno (audio) → { turn_number, reply_text, reply_audio_url }
//   GET   {reply_audio_url}                          → audio de la respuesta del tutor
//   PATCH /api/sessions/{id}  { ended: true }        → termina la sesión (se puede repetir sin problema)
//   GET   /api/sessions/{id}/turns                   → los turnos guardados (transcripciones)
//   GET   /api/sessions/{id}/report                  → informe (409 hasta que la sesión termina)
import { t } from '@/core/i18n.js'
import { API_BASE } from '@/features/app/data/config.js'

// `code` es el identificador estable del backend (detail.code) o uno propio ('network', 'unauthorized'…).
export class ApiError extends Error {
  constructor(code, status = 0) {
    super(code)
    this.code = code
    this.status = status
  }
}

// Texto para el usuario, en el idioma de la interfaz
export function errorText(err) {
  const key = `app.errors.${err?.code}`
  const text = t(key)
  return text === key ? t('app.errors.generic') : text
}

export async function request(path, { method = 'GET', json, body, keepalive = false } = {}) {
  const headers = {}
  if (json) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  }
  let res
  try {
    res = await fetch(`${API_BASE}${path}`, { method, headers, body, keepalive, credentials: 'include' })
  } catch {
    throw new ApiError('network')
  }
  if (!res.ok) {
    let detail = null
    try {
      detail = (await res.json())?.detail
    } catch {
      /* sin cuerpo JSON */
    }
    throw new ApiError(detail?.code || (res.status === 401 ? 'unauthorized' : 'generic'), res.status)
  }
  return res
}

const json = async (res) => res.json()

export const createSession = ({ level, topic, role }) =>
  request('/api/sessions', { method: 'POST', json: { level, topic, ...(role ? { role } : {}) } }).then(json)

// "Ahora tú": evalúa una palabra de la lista de palabras que costaron. El servidor decide si se logró
// y cuántos intentos quedan (POST /api/sessions/{id}/practice, multipart: word + audio).
export function practiceWord(sessionId, word, blob, filename) {
  const form = new FormData()
  form.append('word', word)
  form.append('audio', blob, filename)
  return request(`/api/sessions/${sessionId}/practice`, { method: 'POST', body: form }).then(json)
}

// Guako abre la escena con su primera frase, en el papel elegido (se puede repetir: devuelve la misma)
export const startOpening = (sessionId) => request(`/api/sessions/${sessionId}/opening`, { method: 'POST' }).then(json)

export function sendTurn(sessionId, blob, filename) {
  const form = new FormData()
  form.append('audio', blob, filename)
  return request(`/api/sessions/${sessionId}/turns`, { method: 'POST', body: form }).then(json)
}

// El audio está detrás de la cookie: se descarga con credenciales y se reproduce desde un Blob
export const fetchReplyAudio = (url) => request(url).then((res) => res.blob())

// Dirección para dársela directamente a un <audio>: empieza a sonar mientras se descarga
// (la cookie de sesión viaja igual porque la petición va al mismo sitio).
export const replyAudioSrc = (url) => `${API_BASE}${url}`

// `keepalive` deja que la petición termine aunque la pestaña se esté cerrando
export const endSession = (sessionId, { keepalive = false } = {}) =>
  request(`/api/sessions/${sessionId}`, { method: 'PATCH', json: { ended: true }, keepalive }).then(json)

// Mis conversaciones: las sesiones con al menos un turno, la más reciente primero
export const listSessions = () => request('/api/sessions').then(json)

export const getTurns = (sessionId) => request(`/api/sessions/${sessionId}/turns`).then(json)

// El informe hace una llamada al modelo por turno: se guarda en memoria para que Informe y Revisión
// lo compartan sin repetirlo. Solo se guarda lo que salió bien; `force` lo pide de nuevo.
const reports = new Map()
export async function getReport(sessionId, { force = false } = {}) {
  if (!force && reports.has(sessionId)) return reports.get(sessionId)
  const report = await request(`/api/sessions/${sessionId}/report`).then(json)
  reports.set(sessionId, report)
  return report
}
