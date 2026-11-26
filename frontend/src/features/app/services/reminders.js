// Recordatorio diario de racha (solo en la app móvil): SIEMPRE activo, una notificación local cada día a la
// hora elegida en Ajustes. No se puede apagar desde la app (solo negando el permiso en el teléfono).
//
// Se programan los próximos 7 días como avisos sueltos (no uno que se repite) para poder saltarse HOY cuando
// ya se practicó. Se reprograma al abrir la app, al cambiar la racha, el idioma o la sesión, así que mientras
// se use la app siempre hay una semana por delante. Sin sesión no hay recordatorios.
// Límite: si ese día se practicó en otro dispositivo (la web), este teléfono no lo sabe hasta que se abre la
// app, y el aviso puede llegar igual.
// No usa alarmas exactas (Google Play las restringe): el aviso puede llegar unos minutos tarde.
import { t } from '@/core/i18n.js'
import { isNative } from '@/core/native.js'
import { getSession } from '@/features/auth/index.js'
import { settings, setSetting } from '@/features/app/data/store.js'
import { streak } from '@/features/app/data/streak.js'

const IDS = [101, 102, 103, 104, 105, 106, 107]
export const DEFAULT_HOUR = 19
export const remindersAvailable = isNative

// OJO: nunca devolver el plugin desde una promesa (`.then((m) => m.LocalNotifications)` ni `async` que lo
// retorne): al resolverla, JavaScript le pide `.then` al plugin, Capacitor lo toma como un método nativo y
// falla ("LocalNotifications.then() is not implemented"). Se saca del módulo con desestructuración.
const loadModule = () => import('@capacitor/local-notifications')

export const reminderHour = () => settings().reminderHour ?? DEFAULT_HOUR

// Estado del permiso de notificaciones: 'granted' | 'denied' | 'prompt' (o 'prompt-with-rationale')
export async function notificationPermission() {
  if (!isNative) return 'denied'
  try {
    const { LocalNotifications } = await loadModule()
    return (await LocalNotifications.checkPermissions()).display
  } catch {
    return 'denied'
  }
}

// Pide el permiso (el sistema solo muestra el diálogo si todavía se puede). Devuelve true si quedó concedido.
export async function askNotificationPermission() {
  if (!isNative) return false
  try {
    const { LocalNotifications } = await loadModule()
    const granted = (await LocalNotifications.requestPermissions()).display === 'granted'
    if (granted) await refreshReminder()
    return granted
  } catch {
    return false
  }
}

export async function setReminderHour(hour) {
  setSetting('reminderHour', hour)
  await refreshReminder()
}

// Vuelve a programar los avisos según la hora y si hoy ya se practicó
export async function refreshReminder() {
  if (!isNative) return
  try {
    const { LocalNotifications: notifications } = await loadModule()
    await notifications.cancel({ notifications: IDS.map((id) => ({ id })) })
    if (!getSession() || (await notificationPermission()) !== 'granted') return
    const hour = reminderHour()
    const doneToday = streak()?.status === 'done'
    const now = new Date()
    const list = []
    for (let day = 0; list.length < IDS.length; day++) {
      const at = new Date(now.getFullYear(), now.getMonth(), now.getDate() + day, hour, 0, 0)
      if (at <= now || (day === 0 && doneToday)) continue
      list.push({
        id: IDS[list.length],
        title: t('app.reminder.title'),
        body: t('app.reminder.body'),
        schedule: { at },
        // Sin esto, el plugin abre "Alarmas y recordatorios" de Android para pedir alarmas exactas
        // (permiso que quitamos del manifiesto) y no programa nada.
        isExactNotification: false,
      })
    }
    await notifications.schedule({ notifications: list })
  } catch {
    /* sin permiso o sin plugin: no hay recordatorio, la app sigue igual */
  }
}

// Con sesión y sin haber respondido nunca al permiso, lo pide una vez; después programa los avisos
async function start() {
  if (getSession() && (await notificationPermission()) === 'prompt') await askNotificationPermission()
  await refreshReminder()
}

let started = false
export function initReminders() {
  if (!isNative || started) return
  started = true
  window.addEventListener('streakchange', refreshReminder)
  window.addEventListener('langchange', refreshReminder)
  window.addEventListener('authchange', start)
  start()
}
