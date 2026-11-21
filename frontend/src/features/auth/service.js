// Capa de autenticación del frontend.
//
// El backend todavía no tiene endpoints de autenticación (solo /api/health), así que por
// defecto esto corre en MODO DEMO: no envía correos ni guarda contraseñas, y cualquier
// código OTP válido es MOCK_CODE. Para conectarlo al backend real, define
// VITE_AUTH_MOCK=false y expón estos endpoints (todos POST, JSON, cookie de sesión httpOnly):
//
//   /api/auth/login            { email, password }        → { name, email }
//   /api/auth/register         { name, email, password }  → {}            (envía OTP por correo)
//   /api/auth/register/verify  { email, code }            → { name, email }
//   /api/auth/password/forgot  { email }                  → {}            (responde igual exista o no el correo)
//   /api/auth/password/verify  { email, code }            → { token }
//   /api/auth/password/reset   { token, password }        → {}
//   /api/auth/otp/resend       { email, purpose }         → {}            (purpose: "register" | "reset")
//
// Los errores deben responder { code } con uno de: credentials, badCode, tooMany, expired,
// exists, weak. Cualquier otro se muestra como un error genérico.

export const MOCK = import.meta.env.VITE_AUTH_MOCK !== 'false'
export const MOCK_CODE = '123456'

export class AuthError extends Error {
  constructor(code) {
    super(code)
    this.code = code
  }
}

/* ---------- Validaciones compartidas ---------- */
export const isEmail = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v)
export const isStrongEnough = (v) => v.length >= 8 && /[A-Za-z]/.test(v) && /\d/.test(v)
// 0 = débil, 1 = aceptable, 2 = fuerte
export const passwordScore = (v) => {
  if (!isStrongEnough(v)) return 0
  return v.length >= 12 && /[^A-Za-z0-9]/.test(v) ? 2 : 1
}

/* ---------- Sesión (solo datos no sensibles) ---------- */
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
const wait = (ms = 650) => new Promise((r) => setTimeout(r, ms))
const pending = new Map() // email → { purpose, name, attempts, expires, verified }
const nameOf = (email) => {
  try {
    const map = JSON.parse(localStorage.getItem('guako.names')) || {}
    if (map[email]) return map[email]
  } catch {
    /* ignorar */
  }
  return email
    .split('@')[0]
    .split(/[._-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}
const rememberName = (email, name) => {
  try {
    const map = JSON.parse(localStorage.getItem('guako.names')) || {}
    map[email] = name
    localStorage.setItem('guako.names', JSON.stringify(map))
  } catch {
    /* ignorar */
  }
}
const issue = (email, purpose, extra = {}) =>
  pending.set(email, { purpose, attempts: 0, expires: Date.now() + 10 * 60 * 1000, ...extra })

const checkCode = (email, purpose, code) => {
  const p = pending.get(email)
  if (!p || p.purpose !== purpose) throw new AuthError('expired')
  if (Date.now() > p.expires) throw new AuthError('expired')
  if (p.attempts >= 5) throw new AuthError('tooMany')
  if (code !== MOCK_CODE) {
    p.attempts++
    throw new AuthError(p.attempts >= 5 ? 'tooMany' : 'badCode')
  }
  return p
}

const mock = {
  async login({ email, password }) {
    await wait()
    // Demo: cualquier cuenta funciona, salvo las de @error.test (para ver el error)
    if (email.endsWith('@error.test') || !password) throw new AuthError('credentials')
    return { name: nameOf(email), email }
  },
  async register({ name, email }) {
    await wait()
    if (email === 'existe@guako.test') throw new AuthError('exists')
    issue(email, 'register', { name })
    return {}
  },
  async verifyRegister({ email, code }) {
    await wait(500)
    const p = checkCode(email, 'register', code)
    pending.delete(email)
    rememberName(email, p.name)
    return { name: p.name, email }
  },
  async forgot({ email }) {
    await wait()
    issue(email, 'reset')
    return {}
  },
  async verifyReset({ email, code }) {
    await wait(500)
    checkCode(email, 'reset', code)
    pending.get(email).verified = true
    return { token: `demo-${email}` }
  },
  async reset({ token, password }) {
    await wait()
    const email = token.replace(/^demo-/, '')
    if (!pending.get(email)?.verified) throw new AuthError('expired')
    if (!isStrongEnough(password)) throw new AuthError('weak')
    pending.delete(email)
    return {}
  },
  async resend({ email, purpose }) {
    await wait(450)
    const prev = pending.get(email)
    issue(email, purpose, prev?.name ? { name: prev.name } : {})
    return {}
  },
}

/* ---------- Implementación REAL (HTTP) ---------- */
async function http(path, body) {
  let res
  try {
    res = await fetch(`/api/auth${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    })
  } catch {
    throw new AuthError('network')
  }
  let data = null
  try {
    data = await res.json()
  } catch {
    /* sin cuerpo JSON */
  }
  if (!res.ok) throw new AuthError(data?.code || 'generic')
  return data || {}
}

const real = {
  login: (b) => http('/login', b),
  register: (b) => http('/register', b),
  verifyRegister: (b) => http('/register/verify', b),
  forgot: (b) => http('/password/forgot', b),
  verifyReset: (b) => http('/password/verify', b),
  reset: (b) => http('/password/reset', b),
  resend: (b) => http('/otp/resend', b),
}

export const auth = MOCK ? mock : real
