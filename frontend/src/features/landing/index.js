// Módulo landing (página pública en "/"): API pública.
// Pinta las 4 secciones en orden y arranca sus animaciones.
import './landing.css'
import { addMessages } from '@/core/i18n.js'
import { runCleanups } from '@/core/lifecycle.js'
import es from './i18n/es.js'
import en from './i18n/en.js'
import { renderNavbar, initNavbar } from './components/navbar/navbar.js'
import { renderHero, initHero } from './sections/hero/hero.js'
import { renderRoles, initRoles } from './sections/roles/roles.js'
import { renderHow, initHow } from './sections/how/how.js'
import { renderCta, initCta } from './sections/cta/cta.js'
// Después de las secciones: su CSS (cursor de pluma) debe ganar sobre el de la pila de cartas
import { initFeathers } from './components/feathers/feathers.js'

addMessages({ es, en })

export { updateNavbarAuth } from './components/navbar/navbar.js'

// Se pinta (o se vuelve a pintar, p. ej. al cambiar de idioma) en el idioma actual
export function mountLanding(root) {
  runCleanups()
  root.innerHTML = `
    ${renderNavbar()}
    <main>
      ${renderHero()}
      ${renderRoles()}
      ${renderHow()}
      ${renderCta()}
    </main>
  `
  initNavbar()
  initHero()
  initRoles()
  initHow()
  initCta()
  initFeathers(document.querySelector('.hero__stack'))
}

// Al salir de la landing (p. ej. hacia la app) se deshacen sus listeners y temporizadores
export const unmountLanding = runCleanups
