import './navbar.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t, getLang } from '@/core/i18n.js'
import { listen } from '@/core/lifecycle.js'
import { getSession } from '@/features/auth/index.js'

// Botón de sesión: "Iniciar sesión" (abre el modal) o "Cerrar sesión" si ya hay sesión.
const loginButton = () => {
  const logged = !!getSession()
  return logged
    ? `<button class="btn btn--nav" type="button" data-nav="/app/inicio">${t('nav.app')}</button>`
    : `<button class="btn btn--nav" type="button" data-auth="login">${t('nav.login')}</button>`
}

export function renderNavbar() {
  const lang = getLang()
  const pill = (code) =>
    `<button type="button" data-lang="${code}" aria-pressed="${lang === code}" ${lang === code ? 'class="is-on"' : ''}>${code.toUpperCase()}</button>`
  return `
    <header class="nav" id="nav">
      <div class="nav__bar">
        <a class="nav__brand" href="#" aria-label="${t('nav.home')}">
          <img src="${logo}" alt="" width="40" height="40" />
          <span>GUAKO</span>
        </a>
        <div class="nav__actions">
          <div class="nav__langs" role="group" aria-label="${t('nav.language')}">${pill('es')}${pill('en')}</div>
          <span id="navAuth">${loginButton()}</span>
        </div>
      </div>
    </header>
  `
}

// Actualiza solo el botón de sesión (sin volver a pintar toda la página)
export function updateNavbarAuth() {
  const slot = document.querySelector('#navAuth')
  if (slot) slot.innerHTML = loginButton()
}

// Al hacer scroll el navbar se "contrae" en una píldora flotante.
export function initNavbar() {
  const nav = document.querySelector('#nav')
  const THRESHOLD = 40

  const update = () => {
    nav.classList.toggle('nav--compact', window.scrollY > THRESHOLD)
  }

  listen(window, 'scroll', update, { passive: true })
  update()
}
