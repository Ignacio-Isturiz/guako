// Punto de entrada. Solo hace tres cosas:
//   1. Carga los estilos globales y los módulos (cada módulo registra sus textos y estilos).
//   2. Decide qué módulo se ve según la URL: "/" → landing, "/app/..." → app,
//      "/privacidad", "/terminos", "/borrar-cuenta" (y en inglés) → página legal propia,
//      "/bienvenida" → onboarding. En la app móvil NO hay landing: "/" lleva al onboarding
//      (la primera vez), a la pantalla de acceso o al inicio si ya hay sesión.
//   3. Atiende los clics "accionables" de toda la página (data-nav, data-auth, data-legal...).
import '@/shared/styles/index.css'
import { setLang, applyMeta } from '@/core/i18n.js'
import { navigate } from '@/core/router.js'
import { initNative, isNative } from '@/core/native.js'
import { mountLanding, unmountLanding, updateNavbarAuth } from '@/features/landing/index.js'
import { initAuth, openAuth, logout, getSession } from '@/features/auth/index.js'
import { initLegal, openLegal, legalDocFromPath, mountLegalPage } from '@/features/legal/index.js'
import { isAppPath, mountApp, unmountApp, routeApp, appAction } from '@/features/app/index.js'
import { isOnboardingPath, mountOnboarding, unmountOnboarding, nativeStartPath } from '@/features/onboarding/index.js'

const root = document.querySelector('#app')
let mode = '' // 'landing' | 'app' | 'legal' | 'onboarding'

// Desmonta el módulo actual antes de pasar a otro
function leave(next) {
  if (mode === next) return
  if (mode === 'landing') unmountLanding()
  if (mode === 'app') unmountApp()
  if (mode === 'onboarding') unmountOnboarding()
}

// Fin del onboarding: a la pantalla de acceso y, si eligió, se abre crear cuenta / entrar encima
function finishOnboarding(kind) {
  navigate('/app', { replace: true })
  if (kind) openAuth(kind)
}

function render() {
  const legalDoc = legalDocFromPath()
  if (legalDoc) {
    leave('legal')
    mode = 'legal'
    mountLegalPage(root, legalDoc)
  } else if (isAppPath()) {
    if (mode === 'app') routeApp()
    else {
      leave('app')
      mode = 'app'
      mountApp(root)
    }
  } else if (isOnboardingPath()) {
    leave('onboarding')
    mode = 'onboarding'
    mountOnboarding(root, { onFinish: finishOnboarding })
  } else if (isNative) {
    // La app móvil no tiene landing
    navigate(nativeStartPath(!!getSession()), { replace: true })
  } else {
    leave('landing')
    if (mode !== 'landing') {
      mode = 'landing'
      applyMeta() // título y descripción de la landing (la app cambia el título de la pestaña)
      mountLanding(root)
      window.scrollTo(0, 0)
    }
  }
}

applyMeta()
// El listener va ANTES del primer render: en la app móvil ese render redirige "/" (que no existe) con
// navigate(), y si nadie escucha todavía el routechange, la pantalla se queda vacía.
window.addEventListener('routechange', render)
render()
initNative()

// Cambio de idioma: se repinta el módulo actual conservando la posición del scroll
window.addEventListener('langchange', () => {
  const y = window.scrollY
  if (mode === 'app') {
    unmountApp()
    mountApp(root)
  } else if (mode === 'legal') mountLegalPage(root, legalDocFromPath())
  else if (mode === 'onboarding') mountOnboarding(root, { onFinish: finishOnboarding })
  else mountLanding(root)
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
