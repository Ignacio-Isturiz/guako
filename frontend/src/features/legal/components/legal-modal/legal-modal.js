import './legal-modal.css'
import { t, getLang } from '@/core/i18n.js'
import { createModal } from '@/shared/components/modal/modal.js'
import { renderLegalDoc, initLegalDoc } from '@/features/legal/components/legal-doc/legal-doc.js'

/* ---------------------------------------------------------------------------
   Modal de documentos legales (Términos y Política de privacidad).
   Se abre desde el login/registro y desde el pie de la landing, y también por
   enlace directo: #terminos · #privacidad  (en inglés: #terms · #privacy).
--------------------------------------------------------------------------- */

const SLUGS = {
  es: { terms: 'terminos', privacy: 'privacidad' },
  en: { terms: 'terms', privacy: 'privacy' },
}
const fromHash = (hash) => {
  const h = hash.replace(/^#\/?/, '').toLowerCase()
  if (h === 'terminos' || h === 'terms') return 'terms'
  if (h === 'privacidad' || h === 'privacy') return 'privacy'
  return null
}

let current = 'terms'
let closingFromHash = false

const modal = createModal({
  className: 'modal--legal',
  onClose: () => {
    // Quita el #hash sin recargar ni mover el scroll
    if (fromHash(location.hash) && !closingFromHash) {
      history.replaceState(null, '', location.pathname + location.search)
    }
  },
})
modal.labelledBy('legalTitle')

function render() {
  const tab = (id) =>
    `<button type="button" role="tab" id="tab-${id}" aria-selected="${current === id}" data-doc="${id}" ${current === id ? 'class="is-on"' : ''}>${t(`legal.${id}`)}</button>`

  modal.body.innerHTML = `
    <header class="legal__head">
      <div class="legal__tabs" role="tablist" aria-label="${t('legal.tabs')}">${tab('terms')}${tab('privacy')}</div>
      <button class="modal__close" type="button" data-close aria-label="${t('legal.close')}">×</button>
    </header>
    <div class="legal__scroll" tabindex="0">
      <article class="legal-doc" role="tabpanel" aria-labelledby="tab-${current}">${renderLegalDoc(current)}</article>
    </div>`

  initLegalDoc(modal.body, modal.body.querySelector('.legal__scroll'))
  modal.body.querySelectorAll('[data-doc]').forEach((b) =>
    b.addEventListener('click', () => {
      current = b.dataset.doc
      render()
      setHash()
    }),
  )
}

const setHash = () => {
  const slug = SLUGS[getLang()][current]
  if (location.hash !== `#${slug}`) history.replaceState(null, '', `#${slug}`)
}

export function openLegal(doc = 'terms') {
  current = doc === 'privacy' ? 'privacy' : 'terms'
  render()
  modal.open()
  setHash()
  modal.body.querySelector('.legal__tabs .is-on')?.focus()
}

export function initLegal() {
  // Cambio de idioma con el modal abierto: se vuelve a pintar y se ajusta el enlace
  window.addEventListener('langchange', () => {
    if (!modal.isOpen) return
    render()
    setHash()
  })
  // Enlace directo (#terminos / #privacidad) al cargar y con atrás/adelante
  const sync = () => {
    const doc = fromHash(location.hash)
    if (doc) openLegal(doc)
    else if (modal.isOpen) {
      closingFromHash = true
      modal.close()
      closingFromHash = false
    }
  }
  window.addEventListener('hashchange', sync)
  if (fromHash(location.hash)) openLegal(fromHash(location.hash))
}
