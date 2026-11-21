import pronunciacion from '../assets/benefits/pronunciacion.webp'
import pena from '../assets/benefits/pena.webp'
import gramatica from '../assets/benefits/gramatica.webp'
import entender from '../assets/benefits/entender.webp'
import fluidez from '../assets/benefits/fluidez.webp'
import ritmo from '../assets/benefits/ritmo.webp'
import miedo from '../assets/benefits/miedo.webp'
import seguridad from '../assets/benefits/seguridad.webp'

// Beneficios de Guako: cada ilustración representa lo que dice el título.
const BENEFITS = [
  { title: 'Mejora tu pronunciación', img: pronunciacion },
  { title: 'Quítate la pena al hablar', img: pena },
  { title: 'Corrige tu gramática', img: gramatica },
  { title: 'Date a entender', img: entender },
  { title: 'Gana fluidez', img: fluidez },
  { title: 'Practica a tu ritmo', img: ritmo },
  { title: 'Pierde el miedo a fallar', img: miedo },
  { title: 'Habla con seguridad', img: seguridad },
]

// Palabras que rotan en el titular.
const WORDS = ['confianza', 'fluidez', 'seguridad', 'tu voz']

// Anchos y giros variados: las cartas se ven pegadas a mano, no en cuadrícula.
const WIDTHS = [
  [260, 310, 240, 285, 250, 320, 235, 275],
  [300, 245, 285, 255, 325, 235, 275, 265],
]
const TILTS = [-3, 2.5, -1.5, 3, -2.5, 1.5, -2, 2]

// Configuración de cada franja: sentido, velocidad (px/s) y parallax del mouse.
const STRIPS = [
  { dir: 1, speed: 46, shift: 0, px: -26 },
  { dir: -1, speed: 64, shift: 4, px: 38 },
]

function card(b, i, w, strip) {
  const tilt = TILTS[(i + strip * 3) % TILTS.length]
  // Cada carta flota con su propio ritmo
  const bobDur = 5 + ((i * 7 + strip * 3) % 5) * 0.7
  const bobDelay = -((i * 1.3 + strip) % 5)
  return `
    <article class="card" style="--w:${w}px; --tilt:${tilt}deg; --bd:${bobDur}s; --bdelay:${bobDelay}s">
      <div class="card__inner">
        <div class="card__paper">
          <img src="${b.img}" alt="" width="640" height="640" draggable="false" />
        </div>
        <h3 class="card__label">${b.title}</h3>
      </div>
    </article>
  `
}

function strip(s, index) {
  const items = [...BENEFITS.slice(s.shift), ...BENEFITS.slice(0, s.shift)]
  const html = items.map((b, i) => card(b, i, WIDTHS[index][i], index)).join('')
  // El contenido se duplica para que el bucle sea continuo.
  return `
    <div class="strip strip--${index + 1}" aria-hidden="true">
      <div class="strip__track">${html}${html}</div>
    </div>
  `
}

export function renderHero() {
  return `
    <section class="hero">
      <div class="hero__copy">
        <h1>
          <span class="line line--a">Habla inglés </span><span class="line line--b">con <span class="mark" id="mark"><span class="mark__word" id="word">${WORDS[0]}</span></span>,</span>
          <span class="line">sin pena.</span>
        </h1>
        <p class="hero__lead">
          Mejora tu pronunciación, corrige tu gramática al hablar y date a entender.
          Guako te escucha y te ayuda a perder el miedo.
        </p>
        <div class="hero__cta">
          <a class="btn btn--primary" href="#">Empezar gratis</a>
          <a class="btn btn--ghost" href="#beneficios">Cómo funciona</a>
        </div>
      </div>

      <div class="hero__strips" id="strips">${STRIPS.map(strip).join('')}</div>
    </section>
  `
}

export function initHero() {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches

  /* ---- Palabra rotatoria del titular ---- */
  const mark = document.querySelector('#mark')
  const word = document.querySelector('#word')
  const fit = () => {
    const cs = getComputedStyle(mark)
    mark.style.width = `${word.offsetWidth + parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight)}px`
  }
  document.fonts?.ready.then(fit)
  fit()
  if (!reduced) {
    let w = 0
    setInterval(() => {
      word.classList.add('is-out')
      setTimeout(() => {
        word.textContent = WORDS[++w % WORDS.length]
        word.classList.remove('is-out')
        fit()
      }, 280)
    }, 2800)
  }

  if (reduced) return

  /* ---- Franjas en movimiento continuo ---- */
  const rows = [...document.querySelectorAll('.strip')].map((el, i) => ({
    el,
    track: el.querySelector('.strip__track'),
    ...STRIPS[i],
    x: i * 380, // cada franja arranca en otro punto
    cur: STRIPS[i].speed,
    hover: false,
    W: 1,
  }))
  const measure = () => rows.forEach((r) => (r.W = r.track.scrollWidth / 2))
  measure()
  window.addEventListener('resize', measure)
  window.addEventListener('load', measure)
  document.fonts?.ready.then(measure)

  rows.forEach((r) => {
    r.el.addEventListener('pointerenter', () => (r.hover = true))
    r.el.addEventListener('pointerleave', () => (r.hover = false))
  })

  // Mouse: las franjas se desplazan en sentidos opuestos (parallax)
  let mx = 0
  let my = 0
  let tx = 0
  let ty = 0
  window.addEventListener('pointermove', (e) => {
    tx = e.clientX / innerWidth - 0.5
    ty = e.clientY / innerHeight - 0.5
  })

  // Scroll: la velocidad del scroll acelera las franjas
  let lastY = scrollY
  let boost = 0

  let last = performance.now()
  const frame = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000)
    last = now

    const dy = Math.abs(scrollY - lastY)
    lastY = scrollY
    const impulse = Math.min(8, dy / (dt * 500 || 1))
    boost += (impulse - boost) * Math.min(1, dt * (impulse > boost ? 10 : 2.5))

    mx += (tx - mx) * Math.min(1, dt * 4)
    my += (ty - my) * Math.min(1, dt * 4)

    rows.forEach((r, i) => {
      const target = r.hover ? 0 : r.speed * (1 + boost)
      r.cur += (target - r.cur) * Math.min(1, dt * 5)
      r.x = (((r.x + r.cur * r.dir * dt) % r.W) + r.W) % r.W
      const offX = mx * r.px
      const offY = my * (i ? -10 : 12)
      r.track.style.transform = `translate3d(${-r.x + offX}px, ${offY}px, 0)`
    })
    requestAnimationFrame(frame)
  }
  requestAnimationFrame(frame)
}
