import logo from '../assets/guako-logo.png'
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

// Palabras que rotan en el titular y frases que "dice" Guako.
const WORDS = ['confianza', 'fluidez', 'seguridad', 'tu voz']
const PHRASES = ['Hello!', 'Nice to meet you!', 'How are you today?', 'I can do this!']

// Alturas y giros variados: el muro se ve pegado a mano, no en cuadrícula.
const HEIGHTS = [250, 330, 290, 370, 270, 310, 350, 260]
const TILTS = [-3, 2, -1.5, 3, -2.5, 1.5, -1, 2.5]
const COLUMNS = 4

function card(b, i) {
  return `
    <article class="card" style="--h:${HEIGHTS[i % HEIGHTS.length]}px; --tilt:${TILTS[i % TILTS.length]}deg">
      <div class="card__paper">
        <img src="${b.img}" alt="" width="640" height="640" loading="lazy" />
      </div>
      <h3 class="card__label">${b.title}</h3>
    </article>
  `
}

function column(c) {
  // Cada columna arranca en otro beneficio y con otras alturas.
  const shift = (c * 2) % BENEFITS.length
  const items = [...BENEFITS.slice(shift), ...BENEFITS.slice(0, shift)]
  const html = items.map((b, i) => card(b, i + c * 3)).join('')
  const dir = c % 2 === 0 ? 'up' : 'down'
  // Contenido duplicado: el bucle vertical es continuo.
  return `
    <div class="col col--${dir}" style="--speed:${60 + c * 9}s; --phase:${-(c * 17)}s" aria-hidden="true">
      <div class="col__track">${html}${html}</div>
    </div>
  `
}

export function renderHero() {
  const cols = Array.from({ length: COLUMNS }, (_, c) => column(c)).join('')
  return `
    <section class="hero">
      <div class="hero__copy">
        <h1>
          <span class="line">Habla inglés</span>
          <span class="line">con <span class="mark" id="mark"><span class="mark__word" id="word">${WORDS[0]}</span></span>,</span>
          <span class="line">sin pena.</span>
        </h1>
        <p class="hero__lead">
          Mejora tu pronunciación, corrige tu gramática al hablar y date a entender.
          Guako te escucha y te ayuda a perder el miedo, una conversación a la vez.
        </p>
        <div class="hero__cta">
          <a class="btn btn--primary" href="#">Empezar gratis</a>
          <a class="btn btn--ghost" href="#beneficios">Cómo funciona</a>
        </div>
        <div class="say" aria-live="off">
          <img src="${logo}" alt="" width="44" height="44" />
          <p class="say__bubble"><span class="say__hint">Prueba decir en voz alta:</span> <strong id="phrase">“${PHRASES[0]}”</strong></p>
        </div>
      </div>

      <div class="hero__wall">${cols}</div>
    </section>
  `
}

// Rota la palabra del titular y la frase del globo de diálogo.
export function initHero() {
  const mark = document.querySelector('#mark')
  const word = document.querySelector('#word')
  const phrase = document.querySelector('#phrase')
  if (!mark || !word || !phrase) return

  const fit = () => {
    const cs = getComputedStyle(mark)
    const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight)
    mark.style.width = `${word.offsetWidth + pad}px`
  }
  // Espera a que cargue la tipografía para medir bien el ancho.
  document.fonts?.ready.then(fit)
  fit()

  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return

  const swap = (el, text, wrap = (t) => t) => {
    el.classList.add('is-out')
    setTimeout(() => {
      el.textContent = wrap(text)
      el.classList.remove('is-out')
      if (el === word) fit()
    }, 280)
  }

  let w = 0
  let p = 0
  setInterval(() => swap(word, WORDS[++w % WORDS.length]), 2800)
  setInterval(() => swap(phrase, PHRASES[++p % PHRASES.length], (t) => `“${t}”`), 3400)
}
