import './hero.css'
import '@/features/landing/components/mark/mark.css'
import { t } from '@/core/i18n.js'
import { renderCardStack, initCardStack } from '@/features/landing/components/card-stack/card-stack.js'
import { renderSideColumns } from '@/features/landing/components/side-columns/side-columns.js'
import pronunciacion from '@/features/landing/assets/benefits/pronunciacion.webp'
import pena from '@/features/landing/assets/benefits/pena.webp'
import gramatica from '@/features/landing/assets/benefits/gramatica.webp'
import entender from '@/features/landing/assets/benefits/entender.webp'
import fluidez from '@/features/landing/assets/benefits/fluidez.webp'
import ritmo from '@/features/landing/assets/benefits/ritmo.webp'
import miedo from '@/features/landing/assets/benefits/miedo.webp'
import seguridad from '@/features/landing/assets/benefits/seguridad.webp'

// Sección 1 (Hero): titular con la palabra que cambia + pila de cartas de beneficios.
// Las ilustraciones van por posición; los textos vienen del diccionario (ES/EN).
const IMGS = [pronunciacion, pena, gramatica, entender, fluidez, ritmo, miedo, seguridad]
const benefits = () => t('benefits').map((b, i) => ({ ...b, img: IMGS[i] }))

export function renderHero() {
  const BENEFITS = benefits()
  return `
    <section class="hero">
      ${renderSideColumns(BENEFITS)}

      <div class="hero__copy">
        <h1>
          <span class="line line--a">${t('hero.line1')}</span><span class="line line--b">${t('hero.with')}<span class="mark" id="mark"><span class="mark__word" id="word">${BENEFITS[0].word}</span></span>,</span>
          <span class="line">${t('hero.end')}</span>
        </h1>
        <p class="hero__lead">${t('hero.lead')}</p>
        <div class="hero__cta">
          <button class="btn btn--primary" type="button" data-auth="register">${t('hero.start')}</button>
          <a class="btn btn--ghost" href="#como-funciona">${t('hero.how')}</a>
        </div>
      </div>

      <div class="hero__stack">
        ${renderCardStack(BENEFITS, { ariaLabel: t('hero.stackAria') })}
      </div>
    </section>
  `
}

export function initHero() {
  const BENEFITS = benefits()

  /* ---- Palabra del titular: su "cuadro" se ajusta al ancho de la palabra ---- */
  const mark = document.querySelector('#mark')
  const word = document.querySelector('#word')
  const fit = () => {
    const cs = getComputedStyle(mark)
    mark.style.width = `${word.offsetWidth + parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight)}px`
  }
  document.fonts?.ready.then(fit)
  fit()

  // La palabra cambia junto con la carta de arriba de la pila
  initCardStack(document.querySelector('.hero__stack'), BENEFITS, {
    onChange: (b) => {
      if (b.word !== word.textContent) word.classList.add('is-out')
      setTimeout(() => {
        if (word.textContent !== b.word) {
          word.textContent = b.word
          fit()
        }
        word.classList.remove('is-out')
      }, 140)
    },
  })
}
