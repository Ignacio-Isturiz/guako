// Módulo app (la aplicación con sesión, en "/app/..."): API pública.
// Pinta el marco (menú + barra superior) una sola vez y cambia solo la pantalla de views/.
import './app.css'
import './styles/buttons.css'
import './styles/card.css'
import './styles/progress-bar.css'
import { createScope } from '@/core/lifecycle.js'
import { t, addMessages } from '@/core/i18n.js'
import es from './i18n/es.js'
import en from './i18n/en.js'
import { getSession } from '@/features/auth/index.js'
import { matchRoute } from '@/features/app/routes.js'
import { navigate } from '@/core/router.js'
import { renderShell, updateChrome } from '@/features/app/shell/shell.js'
import { checkTerms } from '@/features/app/shell/terms-gate.js'
import { stopSpeaking } from '@/features/app/services/tts.js'
import { initReminders } from '@/features/app/services/reminders.js'
import { clearDemo, hideBanner } from '@/features/app/data/store.js'
import entrar from '@/features/app/views/entrar/entrar.js'
import inicio from '@/features/app/views/inicio/inicio.js'
import preparar from '@/features/app/views/preparar/preparar.js'
import conversacion from '@/features/app/views/conversacion/conversacion.js'
import informe from '@/features/app/views/informe/informe.js'
import revision from '@/features/app/views/revision/revision.js'
import progreso from '@/features/app/views/progreso/progreso.js'
import conversaciones from '@/features/app/views/conversaciones/conversaciones.js'
import practica from '@/features/app/views/practica/practica.js'
import ejercicios from '@/features/app/views/ejercicios/ejercicios.js'
import ajustes from '@/features/app/views/ajustes/ajustes.js'

// Los textos de la app viven bajo la clave `app` (t('app.home.heroTitle'))
addMessages({ es, en }, 'app')

export { isAppPath } from './routes.js'

// Cada pantalla exporta { head, render, init } (ver views/)
const VIEWS = { inicio, preparar, conversacion, informe, revision, progreso, conversaciones, practica, ejercicios, ajustes }

let container = null
let shellOn = false // ¿el marco (menú + barra superior) está pintado?
const viewScope = createScope()

export function mountApp(root) {
  container = root
  shellOn = false
  document.documentElement.classList.add('is-app')
  routeApp()
  initReminders() // solo en la app móvil; programa el recordatorio de racha si está activado
}

export function unmountApp() {
  viewScope.run()
  stopSpeaking()
  container = null
  shellOn = false
  document.documentElement.classList.remove('is-app')
}

export const isMounted = () => !!container

// Pinta la pantalla que corresponde a la URL actual
export function routeApp() {
  if (!container) return
  viewScope.run()
  stopSpeaking()

  // 1. Entrar: sin sesión no hay app
  if (!getSession()) {
    shellOn = false
    document.title = t('app.entrar.title')
    container.innerHTML = entrar.render()
    entrar.init?.(container, {}, viewScope)
    window.scrollTo(0, 0)
    return
  }

  const m = matchRoute()
  if (!m) return navigate('/app/inicio', { replace: true })
  checkTerms() // una vez por visita: si los documentos cambiaron, pide aceptarlos
  const view = VIEWS[m.route.name]

  // 2. Pantalla completa (conversación): sin menú
  if (m.route.focus) {
    shellOn = false
    container.innerHTML = view.render(m.params)
    document.title = `${view.head(m.params).title} · Guako`
    view.init?.(container, m.params, viewScope)
    window.scrollTo(0, 0)
    return
  }

  // 3. Pantallas normales: el marco se pinta una sola vez
  if (!shellOn) {
    container.innerHTML = renderShell()
    shellOn = true
  }
  const head = view.head(m.params)
  updateChrome(m.route.name, head)
  const host = container.querySelector('#view')
  host.innerHTML = view.render(m.params)
  view.init?.(host, m.params, viewScope)
  window.scrollTo(0, 0)
  host.focus({ preventScroll: true })
}

// Acciones del marco (se delegan desde main.js)
export function appAction(name) {
  if (name === 'demo-hide') {
    hideBanner()
    routeApp()
  } else if (name === 'demo-fresh') {
    clearDemo()
    routeApp()
  }
}
