import './legal-page.css'
import { t, getLang } from '@/core/i18n.js'
import logo from '@/shared/assets/brand/guako-logo.png'
import { renderLegalDoc, initLegalDoc } from '@/features/legal/components/legal-doc/legal-doc.js'

/* ---------------------------------------------------------------------------
   Página propia de cada documento legal, con URL fija para enlazarla desde
   Google Play, App Store y correos: /privacidad · /terminos · /borrar-cuenta
   (en inglés: /privacy · /terms · /delete-account).
   Mismo texto que el modal (legal-doc), pero como página normal con su barra.
--------------------------------------------------------------------------- */

export const LEGAL_PATHS = {
  terms: { es: '/terminos', en: '/terms' },
  privacy: { es: '/privacidad', en: '/privacy' },
  // Página pública para pedir el borrado de la cuenta (la pide el formulario Data safety de Google Play)
  deletion: { es: '/borrar-cuenta', en: '/delete-account' },
}

// '/privacidad' → 'privacy' · '/terms/' → 'terms' · cualquier otra ruta → null
export function legalDocFromPath(pathname = location.pathname) {
  const clean = pathname.replace(/\/+$/, '').toLowerCase()
  return Object.keys(LEGAL_PATHS).find((doc) => Object.values(LEGAL_PATHS[doc]).includes(clean)) || null
}

export function renderLegalPage(current) {
  const lang = getLang()
  const pill = (code) =>
    `<button type="button" data-lang="${code}" aria-pressed="${lang === code}" ${lang === code ? 'class="is-on"' : ''}>${code.toUpperCase()}</button>`
  const tab = (id) =>
    `<a href="${LEGAL_PATHS[id][lang]}" data-nav="${LEGAL_PATHS[id][lang]}" ${current === id ? 'class="is-on" aria-current="page"' : ''}>${t(`legal.${id}`)}</a>`

  return `
    <div class="legal-page">
      <header class="legal-page__bar">
        <a class="legal-page__brand" href="/" data-nav="/" aria-label="${t('legal.home')}">
          <img src="${logo}" alt="Guako" />
        </a>
        <div class="legal-page__langs" role="group" aria-label="${t('legal.language')}">${pill('es')}${pill('en')}</div>
      </header>
      <main class="legal-page__main">
        <nav class="legal__tabs legal-page__tabs" aria-label="${t('legal.tabs')}">${tab('terms')}${tab('privacy')}${tab('deletion')}</nav>
        <article class="legal-doc legal-page__card">${renderLegalDoc(current, { titleTag: 'h1' })}</article>
        <a class="legal-page__back link" href="/" data-nav="/">${t('legal.home')}</a>
      </main>
    </div>`
}

export function mountLegalPage(root, current) {
  root.innerHTML = renderLegalPage(current)
  document.title = `${t(`legal.${current}`)} — Guako`
  initLegalDoc(root)
  window.scrollTo(0, 0)
}
