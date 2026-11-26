import './install-app.css'
import { t } from '@/core/i18n.js'
import { createModal } from '@/shared/components/modal/modal.js'
import { isStandalone } from '@/core/native.js'
import logo from '@/shared/assets/brand/guako-logo.png'

/* ---------------------------------------------------------------------------
   Botón "Instalar la app en el celular" de la landing.
   Detecta el sistema del celular y hace lo que corresponde:
     · Android → Play Store (VITE_PLAY_STORE_URL) o, si aún no hay ficha, el
       cuadro "Instalar aplicación" de Chrome (PWA, necesita public/sw.js) y luego
       "¡Listo! Busca Guako en la pantalla de tu celular"; si Chrome no lo ofrece,
       los pasos a mano.
     · iPhone/iPad → App Store (VITE_APP_STORE_URL) o los pasos de Safari
       ("Compartir → Agregar a inicio").
     · Computador → aviso para abrir la página en el celular.
   Si la página ya corre instalada (pantalla completa), el botón no se pinta.
--------------------------------------------------------------------------- */

const STORE = {
  android: import.meta.env.VITE_PLAY_STORE_URL || '',
  ios: import.meta.env.VITE_APP_STORE_URL || '',
}

// El navegador avisa una sola vez que la web se puede instalar: se guarda el aviso para usarlo al hacer clic
let deferredPrompt = null
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault()
  deferredPrompt = e
})
// Tras instalar, el botón se cambia por "¡Listo! Busca Guako en la pantalla de tu celular"
// (se recuerda mientras la página siga abierta, p. ej. al cambiar de idioma)
let installed = false
function showDone() {
  installed = true
  document.querySelectorAll('[data-install]').forEach((el) => (el.outerHTML = renderDone()))
}
window.addEventListener('appinstalled', () => {
  deferredPrompt = null
  showDone()
})

export function detectOS() {
  const ua = navigator.userAgent || ''
  // iPadOS 13+ se presenta como Mac: se reconoce por la pantalla táctil
  if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return 'ios'
  if (/Android/i.test(ua)) return 'android'
  return 'desktop'
}

const PHONE_ICON = `<svg class="install__icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="2.5" width="12" height="19" rx="2.5"/><path d="M12 7.5v7m-3-3 3 3 3-3M10.5 18.5h3"/></svg>`

const CHECK_ICON = `<svg class="install__icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>`
const renderDone = () => `<p class="install install--done" role="status">${CHECK_ICON}<span>${t('install.done')}</span></p>`

export function renderInstallApp() {
  if (isStandalone) return ''
  if (installed) return renderDone()
  return `<button class="install" type="button" data-install>${PHONE_ICON}<span>${t('install.button')}</span></button>`
}

let modal = null
function openSteps(os) {
  if (!modal) {
    modal = createModal({ className: 'modal--install' })
    modal.labelledBy('installTitle')
  }
  const steps = t(`install.steps.${os}`)
  const stores = ['android', 'ios']
    .filter((k) => STORE[k])
    .map((k) => `<a class="btn btn--primary install__store" href="${STORE[k]}" target="_blank" rel="noopener">${t(`install.store.${k}`)}</a>`)
    .join('')

  modal.body.innerHTML = `
    <button class="modal__close" type="button" data-close aria-label="${t('install.close')}">×</button>
    <img class="install__logo" src="${logo}" alt="" width="72" height="72" />
    <h2 class="install__title" id="installTitle">${t(`install.title.${os}`)}</h2>
    ${
      os === 'desktop'
        ? `<p class="install__text">${t('install.desktop', { url: location.host })}</p>`
        : `<ol class="install__steps">${steps.map((s) => `<li>${s}</li>`).join('')}</ol>`
    }
    ${stores ? `<div class="install__stores">${stores}</div>` : ''}
    <button class="btn install__ok" type="button" data-close>${t('install.ok')}</button>`
  modal.open()
  modal.card.focus()
}

async function install() {
  const os = detectOS()
  if (os !== 'desktop' && STORE[os]) {
    window.location.href = STORE[os]
    return
  }
  // Android: el cuadro "Instalar aplicación" de Chrome, directo (como en el video de F-PAF)
  if (os === 'android' && deferredPrompt) {
    const prompt = deferredPrompt
    deferredPrompt = null // el aviso solo se puede usar una vez
    prompt.prompt()
    const choice = await prompt.userChoice.catch(() => null)
    if (choice?.outcome === 'accepted') showDone()
    return
  }
  openSteps(os)
}

export function initInstallApp(root) {
  root?.querySelector('[data-install]')?.addEventListener('click', install)
}
