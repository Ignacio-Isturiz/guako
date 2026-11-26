// Módulo onboarding (solo app móvil y web instalada): API pública.
// En Android/iOS y en la web instalada no hay landing: la app entra por aquí la primera vez y después va directo al acceso.
import { addMessages } from '@/core/i18n.js'
import { createScope } from '@/core/lifecycle.js'
import { renderOnboarding, initOnboarding } from './onboarding.js'
import es from './i18n/es.js'
import en from './i18n/en.js'

addMessages({ es, en })

export const ONBOARDING_PATH = '/bienvenida'
const SEEN_KEY = 'guako.onboarded'
const scope = createScope()

export const isOnboardingPath = (p = location.pathname) => p.replace(/\/+$/, '') === ONBOARDING_PATH

function onboardingSeen() {
  try {
    return localStorage.getItem(SEEN_KEY) === '1'
  } catch {
    return false
  }
}
function markSeen() {
  try {
    localStorage.setItem(SEEN_KEY, '1')
  } catch {
    /* sin almacenamiento: se vuelve a ver la próxima vez, nada más */
  }
}

// A dónde va la app móvil cuando se abre (o cuando una ruta lleva a la landing, que no existe en móvil):
// con sesión → inicio · primera vez → onboarding · si no → pantalla de acceso de la app
export const nativeStartPath = (hasSession) => (hasSession ? '/app/inicio' : onboardingSeen() ? '/app' : ONBOARDING_PATH)

// onFinish(kind): 'register' | 'login' | null (saltó). El onboarding queda visto en cuanto se termina o se salta.
export function mountOnboarding(root, { onFinish }) {
  scope.run()
  root.innerHTML = renderOnboarding()
  initOnboarding(root, scope, {
    onFinish(kind) {
      markSeen()
      onFinish(kind)
    },
  })
}

export function unmountOnboarding() {
  scope.run()
}
