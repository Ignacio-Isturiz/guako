// Recordatorio diario por Web Push, para la web instalada en el celular (la app nativa usa avisos locales).
// La web no puede programar notificaciones, así que el navegador se suscribe y el backend las envía
// (backend/app/push.py): a la hora elegida, en la zona horaria del teléfono, y solo si ese día no practicó.
//   GET    /api/push/key           → clave pública VAPID (null = el servidor no tiene push configurado)
//   PUT    /api/push/subscription  → guarda la suscripción de este navegador con hora, zona e idioma
// El aviso lo pinta public/sw.js (eventos push y notificationclick).
import { apiUrl } from '@/core/api.js'
import { getLang } from '@/core/i18n.js'
import { isStandalone } from '@/core/native.js'
import { MOCK } from '@/features/auth/index.js'

export const webPushAvailable =
  isStandalone && !MOCK && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

// En iPhone, Safari solo deja pedir el permiso tras un toque del usuario (el botón de Ajustes)
export const canAskWithoutTap = !/iPhone|iPad|iPod/i.test(navigator.userAgent || '')

const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

// 'granted' | 'denied' | 'prompt' (mismo formato que el plugin nativo)
export const webPermission = () => (Notification.permission === 'default' ? 'prompt' : Notification.permission)

export async function askWebPermission() {
  try {
    return (await Notification.requestPermission()) === 'granted'
  } catch {
    return false
  }
}

let keyPromise = null
function publicKey() {
  keyPromise ||= fetch(apiUrl('/api/push/key'), { credentials: 'include' })
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => d.public_key || null)
    .catch(() => {
      keyPromise = null // se reintenta la próxima vez
      return null
    })
  return keyPromise
}

// base64url → bytes (formato que pide pushManager.subscribe)
function keyBytes(b64) {
  const s = atob((b64 + '='.repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(s, (c) => c.charCodeAt(0))
}
const sameKey = (buffer, bytes) => {
  if (!buffer) return false
  const a = new Uint8Array(buffer)
  return a.length === bytes.length && a.every((v, i) => v === bytes[i])
}

// Suscribe este navegador (o actualiza hora/idioma). Sin sesión o sin permiso, se da de baja.
export async function syncWebPush({ hasSession, hour }) {
  const reg = await navigator.serviceWorker.ready
  let sub = await reg.pushManager.getSubscription()
  if (!hasSession || webPermission() !== 'granted') {
    // Al darse de baja, el servicio de push responde 410 al backend y este borra la fila
    if (sub && !hasSession) await sub.unsubscribe()
    return
  }
  const key = await publicKey()
  if (!key) return
  const bytes = keyBytes(key)
  if (sub && !sameKey(sub.options?.applicationServerKey, bytes)) {
    await sub.unsubscribe() // el servidor cambió de claves: la suscripción vieja ya no sirve
    sub = null
  }
  sub ||= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes })
  const { endpoint, keys } = sub.toJSON()
  await fetch(apiUrl('/api/push/subscription'), {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint, keys, hour, tz: tz(), lang: getLang() === 'en' ? 'en' : 'es' }),
  })
}
