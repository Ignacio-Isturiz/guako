import './voice-demo.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t } from '@/core/i18n.js'
import { onCleanup } from '@/core/lifecycle.js'

// Vista previa animada de una práctica de voz. NO usa el micrófono real:
// solo simula "te escucho → marco las palabras → resultado" con frases de ejemplo.

// `miss` = posición de una palabra que "se corrige" (opcional).
const PHRASES = [
  { en: 'Nice to meet you!', es: '¡Mucho gusto!' },
  { en: "I'd like a coffee, please.", es: 'Quisiera un café, por favor.', miss: 3 },
  { en: 'Where is the boarding gate?', es: '¿Dónde está la puerta de embarque?' },
  { en: 'Could I have the check, please?', es: '¿Me trae la cuenta, por favor?', miss: 3 },
]

const MIC = `
  <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden="true">
    <path fill="currentColor" d="M12 15a4 4 0 0 0 4-4V6a4 4 0 0 0-8 0v5a4 4 0 0 0 4 4Zm6-4a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.91V19H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-2.09A6 6 0 0 0 18 11Z"/>
  </svg>`

const clean = (w) => w.replace(/[.,!?¿¡]/g, '')

// attrs: atributos extra para el contenedor (p. ej. data-reveal)
export function renderVoiceDemo({ attrs = '' } = {}) {
  return `
    <div class="demo" id="demo" ${attrs}>
      <span class="demo__tag">${t('cta.tag')}</span>
      <p class="demo__es" id="demoEs"></p>
      <p class="demo__en" id="demoEn" aria-live="polite"></p>

      <div class="demo__row">
        <img class="demo__mascot" src="${logo}" alt="" width="56" height="56" />
        <button class="mic" id="mic" type="button" aria-label="${t('cta.micAria')}">
          <span class="mic__ring"></span><span class="mic__ring mic__ring--b"></span>
          ${MIC}
        </button>
        <div class="wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
      </div>

      <p class="demo__status" id="demoStatus" aria-live="polite"></p>
      <button class="demo__next" id="demoNext" type="button">${t('cta.next')}</button>
    </div>`
}

// `watch`: elemento que debe estar en pantalla para que la demo se anime sola
export function initVoiceDemo(watch) {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
  const demo = document.querySelector('#demo')
  const es = document.querySelector('#demoEs')
  const en = document.querySelector('#demoEn')
  const status = document.querySelector('#demoStatus')
  const mic = document.querySelector('#mic')
  const next = document.querySelector('#demoNext')

  let idx = 0
  let timers = []
  let visible = false
  const later = (fn, ms) => timers.push(setTimeout(fn, ms))
  const stopAll = () => {
    timers.forEach(clearTimeout)
    timers = []
  }
  onCleanup(stopAll)

  const setPhrase = () => {
    const p = PHRASES[idx]
    es.textContent = p.es
    en.innerHTML = p.en
      .split(' ')
      .map((w) => `<span class="w">${w}</span>`)
      .join(' ')
    demo.classList.remove('is-listening', 'is-done')
    status.textContent = t('cta.idle')
  }

  // Resultado final de la frase (todas las palabras marcadas)
  const finish = () => {
    const p = PHRASES[idx]
    const spans = [...en.querySelectorAll('.w')]
    spans.forEach((el, i) => {
      const bad = p.miss === i
      el.classList.toggle('is-ok', !bad)
      el.classList.toggle('is-miss', bad)
    })
    demo.classList.remove('is-listening')
    demo.classList.add('is-done')
    status.textContent =
      p.miss === undefined ? t('cta.perfect') : t('cta.almost', { word: clean(spans[p.miss].textContent) })
  }

  // Secuencia: se escucha → se marcan las palabras una a una → resultado → siguiente frase
  const play = (auto = true) => {
    stopAll()
    setPhrase()
    if (reduced) {
      finish()
      return
    }
    later(() => {
      demo.classList.add('is-listening')
      status.textContent = t('cta.listening')
    }, 500)
    const spans = [...en.querySelectorAll('.w')]
    const t0 = 2100
    later(() => demo.classList.remove('is-listening'), t0)
    spans.forEach((el, i) => {
      later(() => {
        const bad = PHRASES[idx].miss === i
        el.classList.add(bad ? 'is-miss' : 'is-ok')
      }, t0 + 150 + i * 260)
    })
    const tEnd = t0 + 150 + spans.length * 260 + 200
    later(finish, tEnd)
    if (auto) {
      later(() => {
        idx = (idx + 1) % PHRASES.length
        play()
      }, tEnd + 3200)
    }
  }

  mic.addEventListener('click', () => play(visible))
  next.addEventListener('click', () => {
    idx = (idx + 1) % PHRASES.length
    play(visible)
  })

  // Solo se anima mientras está en pantalla
  setPhrase()
  if (reduced) {
    finish()
    return
  }
  const io = new IntersectionObserver(
    ([entry]) => {
      visible = entry.isIntersecting
      if (visible) play()
      else {
        stopAll()
        setPhrase()
      }
    },
    { threshold: 0.5 },
  )
  io.observe(watch)
  onCleanup(() => io.disconnect())
}
