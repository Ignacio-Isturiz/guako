// Punto de entrada. Solo hace tres cosas:
//   1. Carga los estilos globales y los módulos (cada módulo registra sus textos y estilos).
//   2. Decide qué módulo se ve según la URL: "/" → landing, "/app/..." → app.
//   3. Atiende los clics "accionables" de toda la página (data-nav, data-auth, data-legal...).
import '@/shared/styles/index.css'
import { setLang, applyMeta } from '@/core/i18n.js'
import { navigate } from '@/core/router.js'
import { mountLanding, unmountLanding, updateNavbarAuth } from '@/features/landing/index.js'
import { initAuth, openAuth, logout, getSession } from '@/features/auth/index.js'
import { initLegal, openLegal } from '@/features/legal/index.js'
import { isAppPath, mountApp, unmountApp, routeApp, appAction } from '@/features/app/index.js'

const root = document.querySelector('#app')
let mode = '' // 'landing' | 'app'

function render() {
  if (isAppPath()) {
    if (mode === 'landing') unmountLanding()
    if (mode === 'app') routeApp()
    else {
      mode = 'app'
      mountApp(root)
    }
  } else {
    if (mode === 'app') unmountApp()
    if (mode !== 'landing') {
      mode = 'landing'
      applyMeta() // título y descripción de la landing (la app cambia el título de la pestaña)
      mountLanding(root)
      window.scrollTo(0, 0)
    }
  }
}

applyMeta()
render()
window.addEventListener('routechange', render)

// Cambio de idioma: se repinta el módulo actual conservando la posición del scroll
window.addEventListener('langchange', () => {
  const y = window.scrollY
  if (mode === 'app') {
    unmountApp()
    mountApp(root)
  } else mountLanding(root)
  window.scrollTo({ top: y, behavior: 'instant' })
})

// Sesión: se actualiza el navbar de la landing y, en la app, la pantalla (Entrar / contenido)
window.addEventListener('authchange', () => {
  updateNavbarAuth()
  if (mode === 'app') routeApp()
})

// Un solo manejador de clics para todo lo "accionable"
document.addEventListener('click', (e) => {
  const lang = e.target.closest('[data-lang]')
  if (lang) return setLang(lang.dataset.lang)

  // Navegación interna sin recargar (se respeta ctrl/cmd + clic)
  const nav = e.target.closest('[data-nav]')
  if (nav && !(e.metaKey || e.ctrlKey || e.shiftKey)) {
    e.preventDefault()
    return navigate(nav.dataset.nav)
  }

  const authBtn = e.target.closest('[data-auth]')
  if (authBtn) {
    e.preventDefault()
    // Con sesión iniciada, "Empezar gratis" lleva directo a la app
    return getSession() ? navigate('/app/inicio') : openAuth(authBtn.dataset.auth)
  }

  const legalBtn = e.target.closest('[data-legal]')
  if (legalBtn) {
    e.preventDefault()
    return openLegal(legalBtn.dataset.legal)
  }

  const action = e.target.closest('[data-action]')?.dataset.action
  if (action === 'app-logout' || action === 'logout') {
    logout()
    navigate('/')
  } else if (action) appAction(action)
})

initAuth()
initLegal()
