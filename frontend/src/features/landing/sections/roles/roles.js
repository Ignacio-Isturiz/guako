import './roles.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { roleArt } from '@/shared/assets/illustrations/index.js'
import { t } from '@/core/i18n.js'
import { onCleanup } from '@/core/lifecycle.js'
import { initScrollReveal } from '@/features/landing/lib/scroll-reveal.js'
import { renderPhraseCarousel } from '@/features/landing/components/phrase-carousel/phrase-carousel.js'

// Sección 2 (amarilla): roles y temas para hablar, conectados con Guako por flechas.
// Datos de diseño de cada card (los textos vienen del diccionario ES/EN).
// `d` es el momento del scroll (0 a 1) en que cada pieza empieza a entrar.
const ROLE_META = [
  { img: 'entrevistador', tilt: -2, d: 0.12 },
  { img: 'mesero', tilt: 1.5, d: 0.26 },
]
const TOPIC_META = [
  { img: 'viajes', tilt: 2, d: 0.2 },
  { img: 'vida-diaria', tilt: -1.5, d: 0.34 },
]

// Si aún no existe la ilustración, se muestra el logo de Guako como marcador provisional.
const picture = (name) => {
  const src = roleArt(name)
  return `<div class="cardimg ${src ? '' : 'cardimg--ph'}"><img src="${src || logo}" alt="" width="200" height="200" draggable="false" /></div>`
}

const role = (r) => `
  <article class="rcard" data-reveal="left" data-d="${r.d}" style="--tilt:${r.tilt}deg">
    ${picture(r.img)}
    <div class="card__body">
      <span class="rcard__tag">${t('roles.roleTag')}</span>
      <h3>${r.title}</h3>
      <p>${r.text}</p>
    </div>
  </article>`

const topic = (o) => `
  <article class="tpill" data-reveal="right" data-d="${o.d}" style="--tilt:${o.tilt}deg">
    ${picture(o.img)}
    <div class="card__body">
      <span class="tpill__tag">${t('roles.topicTag')}</span>
      <h3>${o.title}</h3>
      <p>${o.text}</p>
    </div>
  </article>`

export function renderRoles() {
  const roles = t('roles.roleList').map((r, i) => ({ ...ROLE_META[i], ...r }))
  const topics = t('roles.topicList').map((o, i) => ({ ...TOPIC_META[i], ...o }))
  return `
    <section class="roles" id="como-funciona">
      <div class="roles__head" data-reveal="up" data-d="0">
        <span class="roles__eyebrow">${t('roles.eyebrow')}</span>
        <h2>${t('roles.title')}</h2>
        <p>${t('roles.intro')}</p>
      </div>

      <div class="roles__stage">
        <svg class="roles__lines" aria-hidden="true"></svg>
        <div class="roles__col roles__col--left">${roles.map(role).join('')}</div>

        <div class="roles__center" data-reveal="pop" data-d="0.06">
          <div class="halo"></div>
          <img class="roles__asset" src="${logo}" alt="${t('roles.assetAlt')}" width="512" height="512" />
          <span class="bubble bubble--a">${t('roles.bubbleA')}</span>
          <span class="bubble bubble--b">${t('roles.bubbleB')}</span>
        </div>

        <div class="roles__col roles__col--right">${topics.map(topic).join('')}</div>
      </div>

      ${renderPhraseCarousel({ label: t('roles.phrasesLabel'), phrases: t('roles.phrases'), attrs: 'data-reveal="up" data-d="0.4"' })}
    </section>
  `
}

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v))
const NS = 'http://www.w3.org/2000/svg'

export function initRoles() {
  const section = document.querySelector('.roles')
  if (!section) return
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches

  const stage = section.querySelector('.roles__stage')
  const svg = section.querySelector('.roles__lines')
  const center = section.querySelector('.roles__center')
  const cards = [...section.querySelectorAll('.rcard, .tpill')]

  /* ---- Flechas: salen de Guako y terminan en cada card ---- */
  let lines = []
  const build = () => {
    const W = stage.offsetWidth
    const H = stage.offsetHeight
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`)
    svg.innerHTML = ''
    // Posiciones de diseño (no cambian con las animaciones de entrada)
    const cx = center.offsetLeft + center.offsetWidth / 2
    const cy = center.offsetTop + center.offsetHeight / 2
    const R = center.offsetWidth / 2 + 3

    lines = cards.map((card) => {
      const fromLeft = card.classList.contains('rcard') // la card está a la izquierda de Guako
      const ey = card.offsetTop + card.offsetHeight / 2
      const tipX = fromLeft ? card.offsetLeft + card.offsetWidth + 3 : card.offsetLeft - 3
      const headLen = 12
      const endX = fromLeft ? tipX + headLen : tipX - headLen

      // Punto de salida: sobre el borde del círculo de Guako, mirando hacia la card
      const a = Math.atan2(ey - cy, tipX - cx)
      const sx = cx + R * Math.cos(a)
      const sy = cy + R * Math.sin(a)
      const dx = endX - sx

      const path = document.createElementNS(NS, 'path')
      path.setAttribute('d', `M${sx} ${sy} C${sx + dx * 0.55} ${sy} ${endX - dx * 0.5} ${ey} ${endX} ${ey}`)
      path.setAttribute('class', 'roles__line')
      svg.appendChild(path)

      const head = document.createElementNS(NS, 'polygon')
      head.setAttribute('points', `${tipX},${ey} ${endX},${ey - 6.5} ${endX},${ey + 6.5}`)
      head.setAttribute('class', 'roles__tip')
      svg.appendChild(head)

      const len = path.getTotalLength()
      path.style.strokeDasharray = len
      return { card, path, head, len }
    })
    draw()
  }

  // Las líneas se dibujan desde Guako hacia la card según el avance del scroll
  const draw = () => {
    lines.forEach(({ card, path, head, len }) => {
      const pi = reduced ? 1 : parseFloat(card.style.getPropertyValue('--pi') || '1')
      path.style.strokeDashoffset = len * (1 - pi)
      head.style.opacity = clamp((pi - 0.85) * 6.7)
    })
  }

  const ro = new ResizeObserver(build)
  ro.observe(stage)
  onCleanup(() => ro.disconnect())
  document.fonts?.ready.then(build)
  build()

  /* ---- Entrada ligada al scroll (y las flechas la acompañan) ---- */
  initScrollReveal(section, { onUpdate: draw })
}
