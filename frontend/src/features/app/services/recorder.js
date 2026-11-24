// Micrófono con MediaRecorder para hablar manteniendo presionado (push-to-talk).
// `openMic()` pide el permiso una sola vez al entrar; después start()/stop() graban cada turno.
import { ApiError } from '@/features/app/data/sessions-api.js'

// Formatos que el backend acepta; se usa el primero que el navegador sepa grabar
const MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']

const extensionOf = (mime) => (mime.includes('mp4') ? 'mp4' : mime.includes('ogg') ? 'ogg' : 'webm')

export async function openMic() {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new ApiError('micUnsupported')
  let stream
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (e) {
    throw new ApiError(e?.name === 'NotAllowedError' || e?.name === 'SecurityError' ? 'micDenied' : 'noMic')
  }
  const mimeType = MIME_TYPES.find((m) => MediaRecorder.isTypeSupported(m))
  let recorder = null
  let chunks = []

  return {
    start() {
      chunks = []
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
      recorder.start()
    },
    // Termina la grabación y devuelve { blob, ext } (o null si no había nada grabando)
    stop() {
      return new Promise((resolve) => {
        if (!recorder || recorder.state === 'inactive') return resolve(null)
        const rec = recorder
        rec.onstop = () => {
          const type = rec.mimeType || mimeType || 'audio/webm'
          resolve({ blob: new Blob(chunks, { type }), ext: extensionOf(type) })
        }
        rec.stop()
      })
    },
    // Descarta lo grabado (soltó muy pronto o la ventana perdió el foco)
    cancel() {
      if (recorder && recorder.state !== 'inactive') {
        recorder.onstop = null
        recorder.stop()
      }
      chunks = []
    },
    // Apaga el micrófono (se ve en el navegador como "grabando" hasta que se cierra)
    close() {
      stream.getTracks().forEach((track) => track.stop())
    },
  }
}
