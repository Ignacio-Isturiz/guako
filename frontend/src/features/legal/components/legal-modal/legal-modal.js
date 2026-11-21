import './legal-modal.css'
import { t, getLang } from '@/core/i18n.js'
import { createModal } from '@/shared/components/modal/modal.js'
import { LEGAL, LEGAL_CONFIG } from '@/features/legal/content.js'

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

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

// Sustituye {company}, {email}, {country}, {date}
const fill = (text) =>
  esc(text).replace(/\{(company|email|country|date)\}/g, (_, k) => {
    if (k === 'country') return LEGAL_CONFIG.country[getLang()]
    if (k === 'date') return t('legal.date')
    return LEGAL_CONFIG[k]
  })

function render() {
  const doc = LEGAL[getLang()][current]
  const tab = (id) =>
    `<button type="button" role="tab" id="tab-${id}" aria-selected="${current === id}" data-doc="${id}" ${current === id ? 'class="is-on"' : ''}>${t(`legal.${id}`)}</button>`

  const toc = doc.sections
    .map((s, i) => `<li><button type="button" class="link" data-jump="${i}">${i + 1}. ${esc(s.h)}</button></li>`)
    .join('')

  const sections = doc.sections
    .map(
      (s, i) => `
      <section id="legal-s${i}">
        <h3>${i + 1}. ${esc(s.h)}</h3>
        ${(s.p || []).map((p) => `<p>${fill(p)}</p>`).join('')}
        ${s.ul ? `<ul>${s.ul.map((li) => `<li>${fill(li)}</li>`).join('')}</ul>` : ''}
        ${s.p2 ? `<p>${fill(s.p2)}</p>` : ''}
      </section>`,
    )
    .join('')

  modal.body.innerHTML = `
    <header class="legal__head">
      <div class="legal__tabs" role="tablist" aria-label="${t('legal.tabs')}">${tab('terms')}${tab('privacy')}</div>
      <button class="modal__close" type="button" data-close aria-label="${t('legal.close')}">×</button>
    </header>
    <div class="legal__scroll" tabindex="0">
      <article role="tabpanel" aria-labelledby="tab-${current}">
        <h2 class="legal__title" id="legalTitle">${t(`legal.${current}`)}</h2>
        <p class="legal__updated">${t('legal.updated', { date: t('legal.date') })}</p>
        <p class="legal__intro">${fill(doc.intro)}</p>
        <nav class="legal__toc" aria-label="${t('legal.contents')}">
          <strong>${t('legal.contents')}</strong>
          <ol>${toc}</ol>
        </nav>
        ${sections}
      </article>
    </div>`

  const scroll = modal.body.querySelector('.legal__scroll')
  modal.body.querySelectorAll('[data-doc]').forEach((b) =>
    b.addEventListener('click', () => {
      current = b.dataset.doc
      render()
      setHash()
    }),
  )
  modal.body.querySelectorAll('[data-jump]').forEach((b) =>
    b.addEventListener('click', () => {
      const el = modal.body.querySelector(`#legal-s${b.dataset.jump}`)
      if (el) scroll.scrollTo({ top: el.offsetTop - 12, behavior: 'smooth' })
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
