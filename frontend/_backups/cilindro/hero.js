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

// El cilindro lleva 16 cartas: los 8 beneficios dos veces para cerrar el círculo.
const RING = [...BENEFITS, ...BENEFITS]
const STEP = 360 / RING.length

function card(b, i) {
  const bobDur = 4.6 + ((i * 5) % 4) * 0.7
  const bobDelay = -((i * 1.7) % 5)
  return `
    <article class="ring__card" style="--i:${i}">
      <div class="ring__inner" style="--bd:${bobDur}s; --bdelay:${bobDelay}s">
        <div class="card__paper">
          <img src="${b.img}" alt="" width="640" height="640" draggable="false" />
        </div>
        <h3 class="card__label">${b.title}</h3>
      </div>
    </article>
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

      <div class="hero__ring" id="ringBox" aria-label="Beneficios de Guako">
        <div class="ring" id="ring" style="--step:${STEP}deg">${RING.map(card).join('')}</div>
      </div>
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

  /* ---- Cilindro de cartas en 3D ---- */
  const box = document.querySelector('#ringBox')
  const ring = document.querySelector('#ring')
  const cards = [...ring.querySelectorAll('.ring__card')]

  let angle = 0 // giro actual del cilindro (grados)
  let vel = 0 // velocidad actual (grados/s)
  const BASE = reduced ? 0 : 9
  let dragging = false
  let hovering = false
  let pendingDx = 0

  // Mouse: inclina un poco el cilindro. Scroll: lo acelera.
  let tx = 0
  let ty = 0
  let mx = 0
  let my = 0
  let lastY = scrollY
  let boost = 0

  const apply = () => {
    ring.style.setProperty('--a', `${angle + mx * 10}deg`)
    ring.style.setProperty('--tilt', `${-my * 7}deg`)
    cards.forEach((el, i) => {
      // Ángulo de la carta respecto al frente, en [-180, 180]
      let t = (((i * STEP + angle) % 360) + 540) % 360 - 180
      const facing = Math.cos((t * Math.PI) / 180)
      el.style.filter = facing > 0 ? `brightness(${0.5 + 0.5 * facing})` : 'none'
    })
  }

  box.addEventListener('pointerenter', () => (hovering = true))
  box.addEventListener('pointerleave', () => (hovering = false))
  box.addEventListener('pointerdown', (e) => {
    dragging = true
    box.setPointerCapture(e.pointerId)
    box.classList.add('is-drag')
  })
  const endDrag = () => {
    dragging = false
    box.classList.remove('is-drag')
  }
  box.addEventListener('pointerup', endDrag)
  box.addEventListener('pointercancel', endDrag)
  box.addEventListener('pointermove', (e) => {
    if (dragging) pendingDx += e.movementX
  })
  window.addEventListener('pointermove', (e) => {
    tx = e.clientX / innerWidth - 0.5
    ty = e.clientY / innerHeight - 0.5
  })

  apply()
  if (reduced) return

  let last = performance.now()
  const frame = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000)
    last = now

    const dy = Math.abs(scrollY - lastY)
    lastY = scrollY
    const impulse = Math.min(9, dy / (dt * 450 || 1))
    boost += (impulse - boost) * Math.min(1, dt * (impulse > boost ? 10 : 2.5))

    mx += (tx - mx) * Math.min(1, dt * 4)
    my += (ty - my) * Math.min(1, dt * 4)

    if (dragging) {
      const d = pendingDx * 0.28
      pendingDx = 0
      angle += d
      vel = dt ? d / dt : 0
    } else {
      // Vuelve a la velocidad base (más lenta al pasar el mouse, más rápida al hacer scroll)
      const target = BASE * (hovering ? 0.25 : 1 + boost)
      vel += (target - vel) * Math.min(1, dt * 2.2)
      angle += vel * dt
    }
    apply()
    requestAnimationFrame(frame)
  }
  requestAnimationFrame(frame)
}
