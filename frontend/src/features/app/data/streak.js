// Racha del usuario. Las reglas viven en el backend (backend/app/streaks.py):
//   · cuenta 1 día por acción clave (terminar una conversación), en la zona horaria del usuario
//   · si falla un día, tiene el siguiente para recuperarla (3 oportunidades por mes, no se acumulan)
//   · si no la aprovecha, la racha se acaba sin gastar nada
//   GET  /api/streak?tz=…            → estado de hoy
//   POST /api/streak/activity?tz=…   → registrar la acción clave
// Con VITE_AUTH_MOCK=true (sin backend) se calcula en el navegador con las conversaciones locales.
import { apiUrl } from '@/core/api.js'
import { MOCK } from '@/features/auth/index.js'
import { conversations } from '@/features/app/data/store.js'

const DAY = 864e5
const MAX_RECOVERIES = 3
const STALE_MS = 60_000

const dayKey = (d) => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
// "2026-11-22" → Date local (sin saltos por zona horaria)
const parseDay = (s) => {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

const EMPTY = {
  count: 0,
  best: 0,
  status: 'none', // none | done | pending | recoverable
  recoveriesLeft: MAX_RECOVERIES,
  recoveriesMax: MAX_RECOVERIES,
  recoveredToday: false,
  today: false, // ¿ya hizo la acción hoy?
  week: [],
}

let state = { ...EMPTY }
let loadedAt = 0

const fromApi = (r) => ({
  count: r.count,
  best: r.best,
  status: r.status,
  recoveriesLeft: r.recoveries_left,
  recoveriesMax: r.recoveries_max,
  recoveredToday: r.recovered_today,
  today: r.status === 'done',
  week: r.week.map((d) => ({ date: parseDay(d.date), done: d.done, recovered: d.recovered, isToday: d.is_today })),
})

// Modo demo: misma idea, solo con los días con conversación (sin oportunidades de recuperar)
function localState() {
  const days = new Set(conversations().map((c) => dayKey(new Date(c.date))))
  const today = days.has(dayKey(new Date()))
  let d = today ? new Date() : new Date(Date.now() - DAY)
  let count = 0
  while (days.has(dayKey(d))) {
    count++
    d = new Date(d.getTime() - DAY)
  }
  const week = Array.from({ length: 7 }, (_, i) => {
    const date = new Date(Date.now() - (6 - i) * DAY)
    return { date, done: days.has(dayKey(date)), recovered: false, isToday: i === 6 }
  })
  return { ...EMPTY, count, best: count, status: today ? 'done' : count ? 'pending' : 'none', today, week }
}

function set(next) {
  state = next
  loadedAt = Date.now()
  window.dispatchEvent(new CustomEvent('streakchange'))
  return state
}

async function call(method, path) {
  const res = await fetch(`${apiUrl(path)}?tz=${encodeURIComponent(tz())}`, { method, credentials: 'include' })
  if (!res.ok) throw new Error(`streak ${res.status}`)
  return fromApi(await res.json())
}

// Lo último que se sabe (sincrónico, para pintar sin esperar)
export const streak = () => (MOCK ? localState() : state)

// Pide el estado al servidor (si ya está fresco no repite la petición)
export async function loadStreak({ force = false } = {}) {
  if (MOCK) return streak()
  if (!force && Date.now() - loadedAt < STALE_MS) return state
  try {
    return set(await call('GET', '/api/streak'))
  } catch {
    return state // sin conexión: se queda lo último que se sabía
  }
}

// Registra la acción clave de hoy (terminar una conversación). Nunca lanza error.
export async function registerActivity() {
  if (MOCK) {
    window.dispatchEvent(new CustomEvent('streakchange'))
    return streak()
  }
  try {
    return set(await call('POST', '/api/streak/activity'))
  } catch {
    return state
  }
}

// Al cambiar de cuenta se descarta lo guardado
window.addEventListener('authchange', () => {
  state = { ...EMPTY }
  loadedAt = 0
})
