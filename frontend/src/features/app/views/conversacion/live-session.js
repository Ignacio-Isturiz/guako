// Conversación real: junta el micrófono, la API de sesiones y la reproducción de la respuesta.
// La pantalla (conversacion.js) solo pinta; todo lo que habla con el backend vive aquí.
import { openMic } from '@/features/app/services/recorder.js'
import { createSession, setAudioConsent, startOpening, sendTurn, fetchReplyAudio, endSession } from '@/features/app/data/sessions-api.js'
import { readAudioConsent } from '@/features/app/data/consent.js'

export function createLiveSession({ level, topic, role }) {
  let mic = null
  let sessionId = null
  let ended = false
  let audio = null
  let audioUrl = null

  const stopPlayback = () => {
    audio?.pause()
    audio = null
  }
  const forgetAudio = () => {
    stopPlayback()
    if (audioUrl) URL.revokeObjectURL(audioUrl)
    audioUrl = null
  }

  // Descarga el audio de una respuesta y lo deja listo; sin audio igual se muestra el texto
  const loadAudio = async (url) => {
    forgetAudio()
    try {
      audioUrl = URL.createObjectURL(await fetchReplyAudio(url))
    } catch {
      audioUrl = null
    }
  }

  return {
    get id() {
      return sessionId
    },

    // Primero el micrófono (si no hay permiso no se crea una sesión vacía) y luego la sesión
    async open() {
      mic = await openMic()
      try {
        sessionId = (await createSession({ level, topic, role })).id
      } catch (e) {
        mic.close()
        mic = null
        throw e
      }
      // "Guardar mi audio": se avisa al backend antes del primer turno. Si esa llamada falla la
      // conversación sigue SIN consentimiento (lo seguro): solo que no se medirá la pronunciación.
      if (readAudioConsent()) await setAudioConsent(sessionId, true).catch(() => {})
    },

    // Guako habla primero: pide su frase de apertura y deja lista su voz. Devuelve { text }.
    async opening() {
      const turn = await startOpening(sessionId)
      await loadAudio(turn.reply_audio_url)
      return { text: turn.reply_text }
    },

    startRecording: () => mic.start(),
    cancelRecording: () => mic?.cancel(),

    // Envía lo grabado y deja lista la respuesta. Devuelve { turnNumber, userText, text } o null si no había audio.
    async sendRecording() {
      const rec = await mic.stop()
      if (!rec) return null
      const turn = await sendTurn(sessionId, rec.blob, `turn.${rec.ext}`)
      await loadAudio(turn.reply_audio_url)
      return { turnNumber: turn.turn_number, userText: turn.user_transcript, text: turn.reply_text }
    },

    // Reproduce la última respuesta; se resuelve cuando termina (o enseguida si no hay audio)
    play() {
      return new Promise((resolve) => {
        if (!audioUrl) return resolve()
        stopPlayback()
        audio = new Audio(audioUrl)
        audio.onended = audio.onerror = () => resolve()
        audio.play().catch(() => resolve())
      })
    },
    stopPlayback,
    hasAudio: () => !!audioUrl,

    // Termina la sesión en el backend (una sola vez; si falla, se puede reintentar)
    async end({ keepalive = false } = {}) {
      if (ended || sessionId == null) return
      ended = true
      try {
        await endSession(sessionId, { keepalive })
      } catch (e) {
        ended = false
        throw e
      }
    },

    dispose() {
      forgetAudio()
      mic?.close()
      mic = null
    },
  }
}
