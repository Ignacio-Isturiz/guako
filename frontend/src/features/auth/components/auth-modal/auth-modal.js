import './auth-modal.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t } from '@/core/i18n.js'
import { navigate } from '@/core/router.js'
import { createModal } from '@/shared/components/modal/modal.js'
import { auth, AuthError, isEmail, isUsername, isStrongEnough, passwordScore, setSession } from '@/features/auth/service.js'

/* ---------------------------------------------------------------------------
   Modal de autenticación. Vistas: login · register
--------------------------------------------------------------------------- */

const KNOWN_ERRORS = ['credentials', 'exists', 'usernameTaken', 'usernameInvalid', 'network']

function fresh() {
  return {
    view: 'login',
    values: { username: '', email: '', password: '', confirm: '', accept: false },
    errors: {},
    formError: '',
    loading: false,
  }
}

let state = fresh()
const modal = createModal({
  className: 'modal--auth',
  onClose: () => {
    state = fresh() // no dejamos contraseñas en memoria
  },
})
modal.labelledBy('authTitle')

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
const legalLink = (doc, label) => `<button type="button" class="link" data-legal="${doc}">${label}</button>`
const legalVars = () => ({ terms: legalLink('terms', t('legal.terms')), privacy: legalLink('privacy', t('legal.privacy')) })

const EYE = `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M12 5c5 0 9 4.5 10 7-1 2.5-5 7-10 7S3 14.5 2 12c1-2.5 5-7 10-7Zm0 2.5A4.5 4.5 0 1 0 12 16.5 4.5 4.5 0 0 0 12 7.5Zm0 2a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5Z"/></svg>`

/* ---------- Piezas de HTML ---------- */
const head = (title, sub) => `
  <button class="modal__close" type="button" data-close aria-label="${t('auth.close')}">×</button>
  <img class="modal__mascot" src="${logo}" alt="" width="64" height="64" />
  <h2 class="modal__title" id="authTitle">${title}</h2>
  ${sub ? `<p class="modal__sub">${sub}</p>` : ''}`

const formError = () => `<p class="form__error" role="alert" ${state.formError ? '' : 'hidden'}>${esc(state.formError)}</p>`

function field({ name, label, type = 'text', autocomplete = 'off', hint = '', focus = false, inputmode = '' }) {
  const err = state.errors[name]
  const pw = type === 'password'
  return `
    <div class="field ${err ? 'has-error' : ''}" data-field="${name}">
      <label for="f-${name}">${label}</label>
      <div class="field__box">
        <input id="f-${name}" name="${name}" type="${type}" value="${esc(state.values[name] ?? '')}"
          autocomplete="${autocomplete}" ${inputmode ? `inputmode="${inputmode}"` : ''}
          ${err ? 'aria-invalid="true"' : ''} aria-describedby="e-${name}" ${focus ? 'data-autofocus' : ''} />
        ${pw ? `<button type="button" class="field__eye" data-toggle="${name}" aria-label="${t('auth.show')}" aria-pressed="false">${EYE}</button>` : ''}
      </div>
      ${hint ? `<small class="field__hint">${hint}</small>` : ''}
      <em class="field__err" id="e-${name}" role="alert">${err ? esc(err) : ''}</em>
    </div>`
}

const meter = () => `<div class="meter" data-meter aria-hidden="true"><i></i><i></i><i></i><span></span></div>`
const submit = (label) => `<button class="btn btn--primary btn--block" type="submit" data-label="${esc(label)}">${label}</button>`

/* ---------- Vistas ---------- */
const views = {
  login: () => `
    ${head(t('auth.login.title'), t('auth.login.subtitle'))}
    <form class="form" novalidate data-form="login">
      ${formError()}
      ${field({ name: 'email', label: t('auth.login.email'), type: 'email', autocomplete: 'email', inputmode: 'email', focus: true })}
      ${field({ name: 'password', label: t('auth.login.password'), type: 'password', autocomplete: 'current-password' })}
      ${submit(t('auth.login.submit'))}
    </form>
    <p class="modal__switch">${t('auth.login.noAccount')} <button type="button" class="link" data-go="register">${t('auth.login.register')}</button></p>
    <p class="modal__legal">${t('auth.legalLine', legalVars())}</p>`,

  register: () => `
    ${head(t('auth.register.title'), t('auth.register.subtitle'))}
    <form class="form" novalidate data-form="register">
      ${formError()}
      ${field({ name: 'username', label: t('auth.register.username'), autocomplete: 'username', hint: t('auth.register.usernameHint'), focus: true })}
      ${field({ name: 'email', label: t('auth.register.email'), type: 'email', autocomplete: 'email', inputmode: 'email' })}
      ${field({ name: 'password', label: t('auth.register.password'), type: 'password', autocomplete: 'new-password', hint: t('auth.register.hint') })}
      ${meter()}
      ${field({ name: 'confirm', label: t('auth.register.confirm'), type: 'password', autocomplete: 'new-password' })}
      <div class="field ${state.errors.accept ? 'has-error' : ''}" data-field="accept">
        <label class="check">
          <input type="checkbox" name="accept" ${state.values.accept ? 'checked' : ''} aria-describedby="e-accept" />
          <span>${t('auth.register.accept', legalVars())}</span>
        </label>
        <em class="field__err" id="e-accept" role="alert">${state.errors.accept ? esc(state.errors.accept) : ''}</em>
      </div>
      ${submit(t('auth.register.submit'))}
    </form>
    <p class="modal__switch">${t('auth.register.hasAccount')} <button type="button" class="link" data-go="login">${t('auth.register.login')}</button></p>`,
}

/* ---------- Render y eventos ---------- */
function render() {
  modal.body.innerHTML = views[state.view]()
  bind()
  updateMeter()
  modal.body.querySelector('[data-autofocus]')?.focus()
}

function go(view) {
  state.view = view
  state.loading = false
  state.errors = {}
  state.formError = ''
  render()
}

function bind() {
  const body = modal.body
  body.querySelectorAll('input[name]').forEach((inp) => inp.addEventListener('input', onInput))
  body.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)))
  body.querySelectorAll('[data-toggle]').forEach((b) =>
    b.addEventListener('click', () => {
      const input = body.querySelector(`#f-${b.dataset.toggle}`)
      const show = input.type === 'password'
      input.type = show ? 'text' : 'password'
      b.setAttribute('aria-pressed', String(show))
      b.setAttribute('aria-label', show ? t('auth.hide') : t('auth.show'))
      b.classList.toggle('is-on', show)
    }),
  )
  body.querySelector('form[data-form]')?.addEventListener('submit', onSubmit)
}

function onInput(e) {
  const { name, type, checked, value } = e.target
  state.values[name] = type === 'checkbox' ? checked : value
  if (state.errors[name]) {
    delete state.errors[name]
    showErrors()
  }
  if (name === 'password') updateMeter()
}

// Barra de fortaleza de la contraseña
function updateMeter() {
  const m = modal.body.querySelector('[data-meter]')
  if (!m) return
  const v = state.values.password
  const score = passwordScore(v)
  const level = !v ? -1 : score
  m.dataset.level = String(level)
  m.querySelectorAll('i').forEach((bar, i) => bar.classList.toggle('on', level >= i && level >= 0))
  m.querySelector('span').textContent = !v ? '' : [t('auth.strength.weak'), t('auth.strength.ok'), t('auth.strength.strong')][score]
}

function showErrors() {
  modal.body.querySelectorAll('.field').forEach((f) => {
    const name = f.dataset.field
    const msg = state.errors[name]
    f.classList.toggle('has-error', !!msg)
    f.querySelector('input')?.[msg ? 'setAttribute' : 'removeAttribute']('aria-invalid', 'true')
    const out = f.querySelector('.field__err')
    if (out) out.textContent = msg || ''
  })
}

function setFormError(msg) {
  state.formError = msg
  const el = modal.body.querySelector('.form__error')
  if (el) {
    el.textContent = msg
    el.hidden = !msg
  }
}

function setLoading(on) {
  state.loading = on
  const btn = modal.body.querySelector('button[type="submit"]')
  if (btn) {
    btn.disabled = on
    btn.textContent = on ? t('auth.loading') : btn.dataset.label
  }
  modal.card.toggleAttribute('aria-busy', on)
}

const msgFor = (err) => {
  const code = err instanceof AuthError && KNOWN_ERRORS.includes(err.code) ? err.code : 'generic'
  return t(`auth.errors.${code}`)
}

/* ---------- Envío de formularios ---------- */
async function onSubmit(e) {
  e.preventDefault()
  if (state.loading) return
  const kind = e.currentTarget.dataset.form

  const v = state.values
  const email = v.email.trim()
  const errors = {}
  const need = (k, val) => !val && (errors[k] = t('auth.errors.required'))

  if (kind === 'login') {
    if (!need('email', email) && !isEmail(email)) errors.email = t('auth.errors.email')
    need('password', v.password)
  } else if (kind === 'register') {
    const username = v.username.trim()
    if (!need('username', username) && !isUsername(username)) errors.username = t('auth.errors.username')
    if (!need('email', email) && !isEmail(email)) errors.email = t('auth.errors.email')
    if (!need('password', v.password) && !isStrongEnough(v.password)) errors.password = t('auth.errors.password')
    if (!errors.password && !need('confirm', v.confirm) && v.confirm !== v.password) errors.confirm = t('auth.errors.mismatch')
    if (!v.accept) errors.accept = t('auth.errors.accept')
  }

  state.errors = errors
  showErrors()
  if (Object.keys(errors).length) {
    modal.body.querySelector(`#f-${Object.keys(errors)[0]}`)?.focus()
    return
  }
  setFormError('')
  setLoading(true)
  try {
    if (kind === 'login') {
      const user = await auth.login({ email, password: v.password })
      finish(user)
    } else if (kind === 'register') {
      const user = await auth.register({ username: v.username.trim(), email, password: v.password })
      finish(user)
    }
  } catch (err) {
    if (err instanceof AuthError && err.code === 'exists') {
      state.errors = { email: t('auth.errors.exists') }
      showErrors()
    } else if (err instanceof AuthError && (err.code === 'usernameTaken' || err.code === 'usernameInvalid')) {
      state.errors = { username: t(`auth.errors.${err.code}`) }
      showErrors()
    } else if (err instanceof AuthError && err.code === 'weak') {
      state.errors = { password: t('auth.errors.password') }
      showErrors()
    } else {
      setFormError(msgFor(err))
    }
    setLoading(false)
  }
}

// Sesión iniciada o cuenta creada: se cierra el modal y se entra a la app
function finish(user) {
  setSession(user)
  modal.close()
  navigate('/app/inicio')
}

/* ---------- API pública ---------- */
export function openAuth(view = 'login') {
  if (!modal.isOpen) state = fresh()
  state.view = view in views ? view : 'login'
  render()
  modal.open()
  modal.body.querySelector('[data-autofocus]')?.focus()
}

export function initAuth() {
  // Si cambia el idioma con el modal abierto, se vuelve a pintar la vista actual
  window.addEventListener('langchange', () => modal.isOpen && render())
}
