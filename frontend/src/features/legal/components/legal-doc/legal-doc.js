import './legal-doc.css'
import { t, getLang } from '@/core/i18n.js'
import { LEGAL, LEGAL_CONFIG } from '@/features/legal/content.js'

/* ---------------------------------------------------------------------------
   Un documento legal completo (título, fecha, introducción, índice y secciones).
   Lo usan el modal (legal-modal) y la página propia (/privacidad, /terminos).
   renderLegalDoc('terms' | 'privacy') → HTML · initLegalDoc(root, scroller) → índice que salta a cada sección.
--------------------------------------------------------------------------- */

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

// Sustituye {company}, {email}, {country}, {date}
const fill = (text) =>
  esc(text).replace(/\{(company|email|country|date)\}/g, (_, k) => {
    if (k === 'country') return LEGAL_CONFIG.country[getLang()]
    if (k === 'date') return t('legal.date')
    return LEGAL_CONFIG[k]
  })

export function renderLegalDoc(current, { titleTag = 'h2' } = {}) {
  const doc = LEGAL[getLang()][current]
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

  return `
    <${titleTag} class="legal__title" id="legalTitle">${t(`legal.${current}`)}</${titleTag}>
    <p class="legal__updated">${t('legal.updated', { date: t('legal.date') })}</p>
    <p class="legal__intro">${fill(doc.intro)}</p>
    <nav class="legal__toc" aria-label="${t('legal.contents')}">
      <strong>${t('legal.contents')}</strong>
      <ol>${toc}</ol>
    </nav>
    ${sections}`
}

// El índice lleva a cada sección. `scroller` es lo que se desplaza: la caja del modal o la ventana.
export function initLegalDoc(root, scroller = window) {
  root.querySelectorAll('[data-jump]').forEach((b) =>
    b.addEventListener('click', () => {
      const el = root.querySelector(`#legal-s${b.dataset.jump}`)
      if (!el) return
      if (scroller === window) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      else scroller.scrollTo({ top: el.offsetTop - 12, behavior: 'smooth' })
    }),
  )
}
