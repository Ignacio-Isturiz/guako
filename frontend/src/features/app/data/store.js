// Datos de la app (modo demo): viven en el navegador, por cuenta, hasta que exista el backend.
// Las conversaciones guardan solo lo dinámico (fecha, puntajes...) y el contenido del
// informe se deriva de la plantilla del tema (ver seed.js).
import { getSession, clearSession, MOCK } from '@/features/auth/index.js'
import { request } from '@/features/app/data/sessions-api.js'
import { TEMPLATES } from '@/features/app/data/seed.js'

export const ASPECTS = ['pron', 'gram', 'fluency', 'clarity', 'listening']
const DAY = 864e5
const VERSION = 1
const SEED_TEMPLATES = ['travel', 'work', 'daily', 'food', 'travel', 'work', 'daily', 'food']
const SEED_DAYS_AGO = [1, 2, 3, 4, 8, 11, 15, 20]

const clamp = (v, a = 40, b = 97) => Math.max(a, Math.min(b, Math.round(v)))
// Variación fija (no aleatoria) para que los datos de ejemplo siempre sean los mismos
const jitter = (seed, i) => ((Math.sin(seed * 12.9898 + i * 78.233) * 43758.5453) % 1) * 5

let cache = null
let cacheKey = ''
const keyOf = () => `guako.app.${getSession()?.email || 'anon'}`

function persist() {
  try {
    localStorage.setItem(cacheKey, JSON.stringify(cache))
  } catch {
    /* sin almacenamiento */
  }
}

function makeScores(templateId, drift, seed) {
  const base = TEMPLATES[templateId].base
  const scores = {}
  ASPECTS.forEach((a, i) => (scores[a] = clamp(base[a] + drift + jitter(seed, i))))
  return scores
}
const overallOf = (scores) => Math.round(ASPECTS.reduce((s, a) => s + scores[a], 0) / ASPECTS.length)

function seedState() {
  const conversations = SEED_TEMPLATES.map((templateId, idx) => {
    const when = new Date(Date.now() - SEED_DAYS_AGO[idx] * DAY)
    when.setHours(18, 30 - idx * 3, 0, 0)
    const scores = makeScores(templateId, 4 - idx * 2, idx + 1)
    return {
      id: `c_seed_${idx + 1}`,
      date: when.toISOString(),
      templateId,
      topicId: templateId,
      topicLabel: '',
      level: 'B1',
      scores,
      overall: overallOf(scores),
      durationMin: 6 + (idx % 4),
      readyAt: 0,
      createdAt: when.getTime(),
    }
  })
  return {
    v: VERSION,
    demo: true,
    bannerHidden: false,
    level: 'B1',
    conversations,
    practice: {},
    settings: { explain: 'es', audio: '30d', sound: true },
  }
}

function read() {
  const k = keyOf()
  if (cache && cacheKey === k) return cache
  cacheKey = k
  try {
    cache = JSON.parse(localStorage.getItem(k))
  } catch {
    cache = null
  }
  if (!cache || cache.v !== VERSION) {
    cache = seedState()
    persist()
  }
  return cache
}
// Si cambia la sesión, se vuelve a leer
window.addEventListener('authchange', () => (cache = null))

/* ---------- Conversaciones ---------- */
const full = (rec) => {
  const t = TEMPLATES[rec.templateId]
  return { ...rec, art: t.art, positive: t.positive, errors: t.errors, phrases: t.phrases, words: t.words, turns: t.turns }
}

export const conversations = () => [...read().conversations].sort((a, b) => new Date(b.date) - new Date(a.date)).map(full)
export const getConversation = (id) => {
  const rec = read().conversations.find((c) => c.id === id)
  return rec ? full(rec) : null
}
export const lastConversation = () => conversations()[0] || null

// Crea la conversación al terminar de hablar. El análisis "se completa" poco a poco (readyAt).
export function createConversation({ templateId, topicId, topicLabel = '', level, turns = 3 }) {
  const state = read()
  const now = Date.now()
  const scores = makeScores(templateId, state.conversations.length ? 1 : 0, now % 97)
  const rec = {
    id: `c_${now.toString(36)}`,
    date: new Date(now).toISOString(),
    templateId,
    topicId,
    topicLabel,
    level,
    scores,
    overall: overallOf(scores),
    durationMin: Math.max(1, Math.round(turns * 0.9 + 2)),
    createdAt: now,
    // Cada aspecto termina de analizarse uno detrás del otro
    readyAt: ASPECTS.map((_, i) => now + 2200 * (i + 1)),
  }
  state.conversations.push(rec)
  state.level = level
  persist()
  return rec.id
}

// Estado de cada aspecto: 'waiting' | 'processing' | 'ready'
export function aspectStatus(conv, now = Date.now()) {
  if (!Array.isArray(conv.readyAt)) return ASPECTS.map(() => 'ready')
  return conv.readyAt.map((at, i) => {
    if (now >= at) return 'ready'
    const prev = i === 0 ? conv.createdAt : conv.readyAt[i - 1]
    return now >= prev ? 'processing' : 'waiting'
  })
}

/* ---------- Práctica ---------- */
export function practiceItems() {
  const seen = new Set()
  const items = []
  conversations().forEach((c) => {
    c.words.forEach((w) => {
      const id = `w:${w.word}`
      if (!seen.has(id)) (seen.add(id), items.push({ id, type: 'word', text: w.word, ipa: w.ipa, tip: w.tip, from: c.id }))
    })
    c.phrases.forEach((p) => {
      const id = `p:${p.better}`
      if (!seen.has(id)) (seen.add(id), items.push({ id, type: 'phrase', text: p.better, said: p.said, why: p.why, from: c.id }))
    })
  })
  return items
}
export const practiceStats = () => read().practice
export function practiceMark(id, ok) {
  const p = read().practice
  const cur = p[id] || { ok: 0, again: 0 }
  cur[ok ? 'ok' : 'again']++
  cur.last = Date.now()
  p[id] = cur
  persist()
}

/* ---------- Ajustes, nivel y estado general ---------- */
export const settings = () => read().settings
export function setSetting(key, value) {
  read().settings[key] = value
  persist()
}
export const level = () => read().level
export const isDemo = () => read().demo
export const bannerHidden = () => read().bannerHidden
export function hideBanner() {
  read().bannerHidden = true
  persist()
}
// "Empezar desde cero": quita los datos de ejemplo
export function clearDemo() {
  const s = read()
  s.conversations = []
  s.practice = {}
  s.demo = false
  s.bannerHidden = true
  persist()
}

export function exportData() {
  const s = read()
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      account: getSession(),
      settings: s.settings,
      level: s.level,
      practice: s.practice,
      conversations: conversations(),
    },
    null,
    2,
  )
}

// Borra la cuenta: primero en el backend (DELETE /api/users/me borra la cuenta, las conversaciones,
// los audios y todo lo demás, y cierra la sesión) y después los datos de este navegador.
// Si el backend falla, lanza el error y no toca nada local: la cuenta sigue existiendo.
export async function deleteAccount() {
  if (!MOCK) await request('/api/users/me', { method: 'DELETE' })
  try {
    localStorage.removeItem(keyOf())
    localStorage.removeItem('guako.names')
  } catch {
    /* ignorar */
  }
  cache = null
  clearSession()
}
