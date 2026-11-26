// Capa de autenticación del frontend.
//
// Habla con el backend (fastapi-users, sesión en cookie httpOnly):
//   POST /api/auth/register  { username, email, password, accept_terms, terms_version }  → crea la cuenta
//   POST /api/auth/login     (formulario: username=<correo>, password) → cookie de sesión
//   POST /api/auth/logout
//   GET  /api/users/me       → { username, email, … }
//
// Con VITE_AUTH_MOCK=true corre en MODO DEMO sin backend (cualquier cuenta funciona).
import { LEGAL_VERSION } from '@/features/legal/index.js'

export const MOCK = import.meta.env.VITE_AUTH_MOCK === 'true'

export class AuthError extends Error {
  constructor(code) {
    super(code)
    this.code = code
  }
}

/* ---------- Validaciones compartidas ---------- */
export const isEmail = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v)
export const isUsername = (v) => /^[A-Za-z0-9_.-]{3,30}$/.test(v)
export const isStrongEnough = (v) => v.length >= 8 && /[A-Za-z]/.test(v) && /\d/.test(v)
// 0 = débil, 1 = aceptable, 2 = fuerte
export const passwordScore = (v) => {
  if (!isStrongEnough(v)) return 0
  return v.length >= 12 && /[^A-Za-z0-9]/.test(v) ? 2 : 1
}

/* ---------- Sesión (solo datos no sensibles; la real vive en la cookie httpOnly) ---------- */
const SESSION_KEY = 'guako.session'

export const getSession = () => {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY)) || null
  } catch {
    return null
  }
}
const emit = () => window.dispatchEvent(new CustomEvent('authchange'))
export const setSession = (s) => {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify({ name: s.name, email: s.email }))
  } catch {
    /* sin almacenamiento */
  }
  emit()
}
export const clearSession = () => {
  try {
    localStorage.removeItem(SESSION_KEY)
  } catch {
    /* sin almacenamiento */
  }
  emit()
}

/* ---------- Implementación DEMO ---------- */
const wait = (ms = 450) => new Promise((r) => setTimeout(r, ms))

const mock = {
  async login({ email, password }) {
    await wait()
    // Demo: cualquier cuenta funciona, salvo las de @error.test (para ver el error)
    if (email.endsWith('@error.test') || !password) throw new AuthError('credentials')
    return { name: email.split('@')[0], email }
  },
  async register({ username, email }) {
    await wait()
    if (username.toLowerCase() === 'existe') throw new AuthError('usernameTaken')
    if (email === 'existe@guako.test') throw new AuthError('exists')
    return { name: username, email }
  },
  async logout() {},
}

/* ---------- Implementación REAL (HTTP) ---------- */
// Traduce las respuestas de error de fastapi-users a nuestros códigos
const codeOf = (detail) => {
  if (typeof detail === 'string') {
    if (detail === 'LOGIN_BAD_CREDENTIALS') return 'credentials'
    if (detail === 'REGISTER_USER_ALREADY_EXISTS') return 'exists'
    return 'generic'
  }
  const code = detail?.code
  return code === 'REGISTER_INVALID_PASSWORD' ? 'weak' : code || 'generic'
}

async function request(path, { method = 'POST', json, form } = {}) {
  const headers = {}
  let body
  if (json) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  } else if (form) {
    body = new URLSearchParams(form) // application/x-www-form-urlencoded
  }
  let res
  try {
    res = await fetch(path, { method, headers, credentials: 'include', body })
  } catch {
    throw new AuthError('network')
  }
  let data = null
  try {
    data = await res.json()
  } catch {
    /* sin cuerpo JSON */
  }
  if (!res.ok) throw new AuthError(codeOf(data?.detail))
  return data
}

async function login({ email, password }) {
  // fastapi-users usa el campo "username" del formulario OAuth2 para el correo
  await request('/api/auth/login', { form: { username: email, password } })
  const me = await request('/api/users/me', { method: 'GET' })
  return { name: me.username, email: me.email }
}

const real = {
  login,
  async register({ username, email, password }) {
    // La casilla "acepto" ya se validó en el formulario; el backend guarda la versión aceptada como prueba.
    await request('/api/auth/register', {
      json: { username, email, password, accept_terms: true, terms_version: LEGAL_VERSION },
    })
    return login({ email, password })
  },
  async logout() {
    await request('/api/auth/logout').catch(() => {})
  },
}

export const auth = MOCK ? mock : real

// Cierra la sesión en el servidor (borra la cookie) y en el navegador
export async function logout() {
  await auth.logout()
  clearSession()
}
