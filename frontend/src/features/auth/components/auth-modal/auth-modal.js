import './auth-modal.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t } from '@/core/i18n.js'
import { createModal } from '@/shared/components/modal/modal.js'
import { auth, AuthError, MOCK, MOCK_CODE, isEmail, isStrongEnough, passwordScore, setSession } from '@/features/auth/service.js'

/* ---------------------------------------------------------------------------
   Modal de autenticación. Vistas:
   login · register · otp (verificar correo / código de recuperación) · forgot · reset · done
--------------------------------------------------------------------------- */

const RESEND_SECONDS = 30
const KNOWN_ERRORS = ['credentials', 'badCode', 'tooMany', 'expired', 'exists', 'network']

function fresh() {
  return {
    view: 'login',
    values: { name: '', email: '', password: '', confirm: '', accept: false },
    errors: {},
    formError: '',
    notice: '',
    loading: false,
    context: 'register', // para qué es el código OTP: 'register' | 'reset'
    otp: '',
    token: '',
    resendAt: 0,
    doneKind: 'login',
    user: null,
  }
}

let state = fresh()
let timer = 0
const modal = createModal({
  className: 'modal--auth',
  onClose: () => {
    stopTimer()
    state = fresh() // no dejamos contraseñas ni códigos en memoria
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
const noticeHtml = () => `<p class="form__notice" role="status" ${state.notice ? '' : 'hidden'}>${esc(state.notice)}</p>`

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
      <button type="button" class="link link--right" data-go="forgot">${t('auth.login.forgot')}</button>
      ${submit(t('auth.login.submit'))}
    </form>
    <p class="modal__switch">${t('auth.login.noAccount')} <button type="button" class="link" data-go="register">${t('auth.login.register')}</button></p>
    <p class="modal__legal">${t('auth.legalLine', legalVars())}</p>`,

  register: () => `
    ${head(t('auth.register.title'), t('auth.register.subtitle'))}
    <form class="form" novalidate data-form="register">
      ${formError()}
      ${field({ name: 'name', label: t('auth.register.name'), autocomplete: 'name', focus: true })}
      ${field({ name: 'email', label: t('auth.register.email'), type: 'email', autocomplete: 'email', inputmode: 'email' })}
      ${field({ name: 'password', label: t('auth.register.password'), type: 'password', autocomplete: 'new-password', hint: t('auth.register.hint') })}
      ${meter()}
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

  otp: () => {
    const reg = state.context === 'register'
    const email = `<strong>${esc(state.values.email)}</strong>`
    const boxes = Array.from(
      { length: 6 },
      (_, i) =>
        `<input class="otp__d" inputmode="numeric" pattern="[0-9]*" maxlength="1" autocomplete="${i === 0 ? 'one-time-code' : 'off'}"
          aria-label="${t('auth.otp.digit', { n: i + 1 })}" value="${esc(state.otp[i] || '')}" ${i === 0 ? 'data-autofocus' : ''} />`,
    ).join('')
    return `
    ${head(reg ? t('auth.otp.registerTitle') : t('auth.otp.resetTitle'), t(reg ? 'auth.otp.registerSubtitle' : 'auth.otp.resetSubtitle', { email }))}
    ${MOCK ? `<p class="modal__demo">${t('auth.demo', { code: MOCK_CODE })}</p>` : ''}
    <form class="form" novalidate data-form="otp">
      ${formError()}
      ${noticeHtml()}
      <fieldset class="otp" aria-label="${t('auth.otp.label')}">
        <legend>${t('auth.otp.label')}</legend>
        <div class="otp__row">${boxes}</div>
      </fieldset>
      <p class="modal__small">${t('auth.otp.expires')}</p>
      ${submit(t('auth.otp.submit'))}
    </form>
    <p class="modal__switch">
      <button type="button" class="link" data-resend>${t('auth.otp.resend')}</button>
      · <button type="button" class="link" data-go="${reg ? 'register' : 'forgot'}">${t('auth.otp.change')}</button>
    </p>`
  },

  forgot: () => `
    ${head(t('auth.forgot.title'), t('auth.forgot.subtitle'))}
    <form class="form" novalidate data-form="forgot">
      ${formError()}
      ${field({ name: 'email', label: t('auth.login.email'), type: 'email', autocomplete: 'email', inputmode: 'email', focus: true })}
      ${submit(t('auth.forgot.submit'))}
    </form>
    <p class="modal__switch"><button type="button" class="link" data-go="login">${t('auth.forgot.back')}</button></p>`,

  reset: () => `
    ${head(t('auth.reset.title'), t('auth.reset.subtitle'))}
    <form class="form" novalidate data-form="reset">
      ${formError()}
      ${field({ name: 'password', label: t('auth.reset.password'), type: 'password', autocomplete: 'new-password', hint: t('auth.register.hint'), focus: true })}
      ${meter()}
      ${field({ name: 'confirm', label: t('auth.reset.confirm'), type: 'password', autocomplete: 'new-password' })}
      ${submit(t('auth.reset.submit'))}
    </form>`,

  done: () => {
    const k = state.doneKind
    const name = esc(state.user?.name || '')
    const title = t(`auth.done.${k}Title`)
    const text = t(`auth.done.${k}Text`, { name })
    const action =
      k === 'reset'
        ? `<button class="btn btn--primary btn--block" type="button" data-go="login" data-autofocus>${t('auth.done.toLogin')}</button>`
        : `<button class="btn btn--primary btn--block" type="button" data-close data-nav="/app/inicio" data-autofocus>${t('auth.done.close')}</button>`
    return `
    <button class="modal__close" type="button" data-close aria-label="${t('auth.close')}">×</button>
    <div class="done">
      <img class="modal__mascot modal__mascot--big" src="${logo}" alt="" width="96" height="96" />
      <h2 class="modal__title" id="authTitle">${title}</h2>
      <p class="modal__sub">${text}</p>
      ${action}
    </div>`
  },
}

/* ---------- Render y eventos ---------- */
function render() {
  modal.body.innerHTML = views[state.view]()
  bind()
  updateMeter()
  if (state.view === 'otp') startTimer()
  else stopTimer()
  modal.body.querySelector('[data-autofocus]')?.focus()
}

function go(view) {
  state.view = view
  state.loading = false
  state.errors = {}
  state.formError = ''
  state.notice = ''
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
  body.querySelector('[data-resend]')?.addEventListener('click', onResend)
  body.querySelector('form[data-form]')?.addEventListener('submit', onSubmit)
  if (state.view === 'otp') bindOtp()
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

function setNotice(msg) {
  state.notice = msg
  const el = modal.body.querySelector('.form__notice')
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
  if (kind === 'otp') return submitOtp()

  const v = state.values
  const email = v.email.trim()
  const errors = {}
  const need = (k, val) => !val && (errors[k] = t('auth.errors.required'))

  if (kind === 'login') {
    if (!need('email', email) && !isEmail(email)) errors.email = t('auth.errors.email')
    need('password', v.password)
  } else if (kind === 'register') {
    need('name', v.name.trim())
    if (!need('email', email) && !isEmail(email)) errors.email = t('auth.errors.email')
    if (!need('password', v.password) && !isStrongEnough(v.password)) errors.password = t('auth.errors.password')
    if (!v.accept) errors.accept = t('auth.errors.accept')
  } else if (kind === 'forgot') {
    if (!need('email', email) && !isEmail(email)) errors.email = t('auth.errors.email')
  } else if (kind === 'reset') {
    if (!need('password', v.password) && !isStrongEnough(v.password)) errors.password = t('auth.errors.password')
    if (!errors.password && !need('confirm', v.confirm) && v.confirm !== v.password) errors.confirm = t('auth.errors.mismatch')
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
      finish('login', user)
    } else if (kind === 'register') {
      await auth.register({ name: v.name.trim(), email, password: v.password })
      state.values.email = email
      state.context = 'register'
      state.otp = ''
      state.resendAt = Date.now() + RESEND_SECONDS * 1000
      go('otp')
    } else if (kind === 'forgot') {
      await auth.forgot({ email })
      state.values.email = email
      state.context = 'reset'
      state.otp = ''
      state.resendAt = Date.now() + RESEND_SECONDS * 1000
      go('otp')
    } else if (kind === 'reset') {
      await auth.reset({ token: state.token, password: v.password })
      state.values.password = ''
      state.values.confirm = ''
      state.token = ''
      state.doneKind = 'reset'
      go('done')
    }
  } catch (err) {
    if (err instanceof AuthError && err.code === 'exists') {
      state.errors = { email: t('auth.errors.exists') }
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

// Sesión iniciada o cuenta verificada
function finish(kind, user) {
  setSession(user)
  state.user = user
  state.doneKind = kind
  state.values.password = ''
  go('done')
}

/* ---------- Código OTP ---------- */
function bindOtp() {
  const boxes = [...modal.body.querySelectorAll('.otp__d')]
  const sync = () => (state.otp = boxes.map((b) => b.value).join(''))
  boxes.forEach((b, i) => {
    b.addEventListener('input', () => {
      b.value = b.value.replace(/\D/g, '').slice(-1)
      sync()
      setFormError('')
      if (b.value && i < 5) boxes[i + 1].focus()
      if (state.otp.length === 6) submitOtp()
    })
    b.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !b.value && i > 0) {
        e.preventDefault()
        boxes[i - 1].value = ''
        boxes[i - 1].focus()
        sync()
      } else if (e.key === 'ArrowLeft' && i > 0) boxes[i - 1].focus()
      else if (e.key === 'ArrowRight' && i < 5) boxes[i + 1].focus()
    })
    b.addEventListener('paste', (e) => {
      e.preventDefault()
      const digits = (e.clipboardData?.getData('text') || '').replace(/\D/g, '').slice(0, 6)
      if (!digits) return
      boxes.forEach((box, k) => (box.value = digits[k] || ''))
      sync()
      boxes[Math.min(digits.length, 5)].focus()
      if (state.otp.length === 6) submitOtp()
    })
    b.addEventListener('focus', () => b.select())
  })
}

async function submitOtp() {
  if (state.loading) return
  if (state.otp.length < 6) {
    setFormError(t('auth.errors.code'))
    return
  }
  setFormError('')
  setNotice('')
  setLoading(true)
  try {
    const email = state.values.email
    if (state.context === 'register') {
      const user = await auth.verifyRegister({ email, code: state.otp })
      finish('register', user)
    } else {
      const { token } = await auth.verifyReset({ email, code: state.otp })
      state.token = token
      state.otp = ''
      go('reset')
    }
  } catch (err) {
    setFormError(msgFor(err))
    setLoading(false)
    // Si el código quedó bloqueado o venció, se puede pedir uno nuevo de inmediato
    if (err instanceof AuthError && (err.code === 'tooMany' || err.code === 'expired')) {
      state.resendAt = 0
      tick()
    }
    const boxes = [...modal.body.querySelectorAll('.otp__d')]
    boxes.forEach((b) => (b.value = ''))
    state.otp = ''
    const row = modal.body.querySelector('.otp__row')
    row?.classList.remove('is-shake')
    void row?.offsetWidth
    row?.classList.add('is-shake')
    boxes[0]?.focus()
  }
}

async function onResend() {
  if (Date.now() < state.resendAt || state.loading) return
  state.loading = true
  try {
    await auth.resend({ email: state.values.email, purpose: state.context })
    state.resendAt = Date.now() + RESEND_SECONDS * 1000
    state.otp = ''
    modal.body.querySelectorAll('.otp__d').forEach((b) => (b.value = ''))
    modal.body.querySelector('.otp__d')?.focus()
    setFormError('')
    setNotice(t('auth.otp.resent'))
    startTimer()
  } catch (err) {
    setFormError(msgFor(err))
  } finally {
    state.loading = false
  }
}

// Cuenta atrás para poder reenviar el código
function tick() {
  const btn = modal.body.querySelector('[data-resend]')
  if (!btn) return stopTimer()
  const left = Math.max(0, Math.ceil((state.resendAt - Date.now()) / 1000))
  btn.disabled = left > 0
  btn.textContent = left > 0 ? t('auth.otp.resendIn', { s: left }) : t('auth.otp.resend')
}
function startTimer() {
  stopTimer()
  tick()
  timer = setInterval(tick, 500)
}
function stopTimer() {
  clearInterval(timer)
  timer = 0
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
