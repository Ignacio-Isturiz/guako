// Autorizaciones del usuario (Ley 1581), guardadas en el SERVIDOR: el backend conserva la prueba (fecha,
// versión, IP) y decide con ellas. Aquí solo hay una copia en memoria para pintar sin esperar.
//   GET  /api/consents/me                         → { terms: { up_to_date, current_version… }, audio: { granted } }
//   POST /api/consents { kind, granted, version? } → el estado nuevo
//
// "Guardar mi audio" viene DESACTIVADO hasta que la persona diga que sí (granted: null = aún no se le preguntó).
import { getSession } from '@/features/auth/index.js'
import { LEGAL_VERSION } from '@/features/legal/index.js'
import { request } from '@/features/app/data/sessions-api.js'

let cache = null // { email, state }

const mine = () => (cache && cache.email === getSession()?.email ? cache.state : null)
const keep = (state) => {
  cache = { email: getSession()?.email, state }
  return state
}

const send = (json) => request('/api/consents', { method: 'POST', json }).then((r) => r.json()).then(keep)

// Trae el estado del servidor (una vez por cuenta, salvo `fresh`). Sin conexión devuelve null.
export async function loadConsents({ fresh = false } = {}) {
  if (mine() && !fresh) return mine()
  try {
    return keep(await request('/api/consents/me').then((r) => r.json()))
  } catch {
    return null
  }
}

// true / false según respondió; null si nunca se le preguntó (o aún no se cargó): se trata como "no".
export const readAudioConsent = () => mine()?.audio?.granted ?? null

export const writeAudioConsent = (on) => send({ kind: 'audio', granted: !!on })

// false solo cuando el servidor dijo que hay una versión nueva sin aceptar (sin datos, no se molesta).
export const termsUpToDate = () => mine()?.terms?.up_to_date !== false

export const acceptTerms = () => send({ kind: 'terms', granted: true, version: LEGAL_VERSION })
