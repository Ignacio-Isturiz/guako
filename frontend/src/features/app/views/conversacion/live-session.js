// Conversación real: junta el micrófono, la API de sesiones y la reproducción de la respuesta.
// La pantalla (conversacion.js) solo pinta; todo lo que habla con el backend vive aquí.
import { openMic } from '@/features/app/services/recorder.js'
import { createSession, setAudioConsent, startOpening, sendTurn, replyAudioSrc, endSession } from '@/features/app/data/sessions-api.js'
import { readAudioConsent } from '@/features/app/data/consent.js'
import { speak, stopSpeaking } from '@/features/app/services/tts.js'

export function createLiveSession({ level, topic, role }) {
  let mic = null
  let sessionId = null
  let ended = false
  // <audio> de la última respuesta. Se crea apenas llega el turno, así el navegador ya la está
  // descargando mientras se pinta el texto, y suena en cuanto hay datos (sin esperar el archivo entero).
  let player = null

  const stopPlayback = () => {
    if (player) {
      player.pause()
      player.currentTime = 0
    }
    stopSpeaking()
  }
  const forgetAudio = () => {
    stopPlayback()
    if (player) {
      player.removeAttribute('src')
      player.load() // corta la descarga en curso
    }
    player = null
  }

  // Texto de la última respuesta cuando no hay audio (todas las voces del servidor estaban agotadas):
  // se lee en voz alta con la voz del navegador.
  let spokenText = ''

  // Deja lista la voz de una respuesta (empieza a descargarse ya); sin audio igual se muestra el texto
  const loadAudio = (url, text = '') => {
    forgetAudio()
    spokenText = url ? '' : text
    if (!url) return
    player = new Audio(replyAudioSrc(url))
    player.preload = 'auto'
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
      await loadAudio(turn.reply_audio_url, turn.reply_text)
      return { text: turn.reply_text }
    },

    startRecording: () => mic.start(),
    cancelRecording: () => mic?.cancel(),

    // Envía lo grabado y deja lista la respuesta. Devuelve { turnNumber, userText, text } o null si no había audio.
    async sendRecording() {
      const rec = await mic.stop()
      if (!rec) return null
      const turn = await sendTurn(sessionId, rec.blob, `turn.${rec.ext}`)
      await loadAudio(turn.reply_audio_url, turn.reply_text)
      return { turnNumber: turn.turn_number, userText: turn.user_transcript, text: turn.reply_text }
    },

    // Reproduce la última respuesta; se resuelve cuando termina (o enseguida si no hay audio)
    play() {
      return new Promise((resolve) => {
        if (!player) {
          if (!spokenText) return resolve()
          // Sin audio del servidor: la voz del navegador lee la respuesta (respeta el ajuste de voz de Guako)
          stopPlayback()
          return speak(spokenText).then(resolve, resolve)
        }
        stopPlayback()
        player.onended = player.onerror = () => resolve()
        player.play().catch(() => resolve())
      })
    },
    stopPlayback,
    hasAudio: () => !!player || !!spokenText,

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
