import './how.css'
import '@/features/landing/components/mark/mark.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t } from '@/core/i18n.js'
import { initScrollReveal } from '@/features/landing/lib/scroll-reveal.js'

// Sección 3 (roja): "¿Cómo aprenderás?" con un collage de papel recortado.
// Imágenes de cada opción: se leen de features/landing/assets/how/<nombre>.webp
// (voz, escucha, correccion, retos). Mientras no exista el archivo,
// se muestra el logo de Guako como marcador provisional.
const ART = import.meta.glob('../../assets/how/*.webp', { eager: true, query: '?url', import: 'default' })
const art = (name) => ART[`../../assets/how/${name}.webp`]

// Imagen de cada una de las 4 opciones (3 en el collage y la cuarta en la barra ancha).
const OPTION_IMGS = ['voz', 'escucha', 'correccion', 'retos']

const src = (name) => art(name) || logo
const ph = (name) => (art(name) ? '' : 'is-ph')

const point = (p, i) => `
  <li data-reveal="left" data-d="${0.08 + i * 0.1}">
    <b>${p.title}</b>
    <span>${p.text}</span>
  </li>`

const blob = (o, tilt) => `
  <figure class="blob blob--${o.n} ${ph(o.img)}" data-reveal="${o.n === 3 ? 'up' : 'right'}" data-d="${0.1 + o.n * 0.1}" style="--tilt:${tilt}deg">
    <div class="blob__shape"><img src="${src(o.img)}" alt="" width="420" height="420" draggable="false" /></div>
    <span class="blob__num">${o.n}</span>
    <figcaption class="blob__cap"><strong>${o.title}</strong><small>${o.text}</small></figcaption>
  </figure>`

export function renderHow() {
  const [o1, o2, o3, o4] = t('how.options').map((o, i) => ({ ...o, n: i + 1, img: OPTION_IMGS[i] }))
  const POINTS = t('how.points')
  return `
    <section class="how" id="como-aprenderas">
      <div class="how__inner">
        <div class="how__copy">
          <h2 data-reveal="left" data-d="0">${t('how.titleA')}<span class="mark">${t('how.titleMark')}</span>${t('how.titleB')}</h2>
          <ul class="how__list">${POINTS.map(point).join('')}</ul>
        </div>

        <div class="how__options">
          <div class="how__label" data-reveal="up" data-d="0.08">
            <span>${t('how.label')}</span>
            <svg viewBox="0 0 70 70" width="58" height="58" aria-hidden="true">
              <path d="M8 6 C48 2 66 28 40 56" fill="none" stroke="#fff6e0" stroke-width="3.5" stroke-linecap="round"/>
              <path d="M30 58 L41 58 L40 46" fill="none" stroke="#fff6e0" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>

          <div class="how__gallery">
            ${blob(o1, -3)}${blob(o2, 2.5)}${blob(o3, -1.5)}
          </div>

          <div class="how__bar ${ph(o4.img)}" data-reveal="up" data-d="0.45">
            <span class="how__barnum">${o4.n}</span>
            <div class="how__bartext"><strong>${o4.title}</strong><small>${o4.text}</small></div>
            <div class="how__barimg"><img src="${src(o4.img)}" alt="" width="600" height="200" draggable="false" /></div>
          </div>
        </div>
      </div>
    </section>
  `
}

// Las piezas entran mientras el usuario hace scroll (igual que la sección anterior).
export function initHow() {
  initScrollReveal(document.querySelector('.how'))
}
