import './card-stack.css'
import { onCleanup } from '@/core/lifecycle.js'

// Pila de cartas de papel: cambia sola cada pocos segundos y también al deslizarla.
// items: [{ img, title, text }] → la carta muestra img + title y la leyenda de abajo muestra text.

const card = (item, i) => `
  <article class="stack__card" data-i="${i}" style="--s:${i % 2 ? 1 : -1}">
    <div class="card__paper">
      <img src="${item.img}" alt="" width="640" height="640" draggable="false" />
    </div>
    <h3 class="card__label">${item.title}</h3>
  </article>
`

export function renderCardStack(items, { ariaLabel = '' } = {}) {
  return `
    <div class="stack-wrap">
      <div class="stack" id="stack" aria-label="${ariaLabel}">${items.map(card).join('')}</div>
    </div>
    <p class="stack__caption" id="caption" aria-live="polite">${items[0].text}</p>
  `
}

// onChange(item) se llama cada vez que cambia la carta de arriba
export function initCardStack(root, items, { onChange, interval = 3400 } = {}) {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
  const stack = root.querySelector('#stack')
  const caption = root.querySelector('#caption')
  const els = [...stack.querySelectorAll('.stack__card')]
  // order[0] es la carta de arriba
  let order = els.map((_, i) => i)
  let busy = false

  const render = () => {
    order.forEach((idx, p) => {
      const el = els[idx]
      el.style.setProperty('--p', p)
      el.style.zIndex = el.classList.contains('is-flying') ? 200 : 100 - p
      // Solo se ven las 4 de arriba; el resto espera escondido
      el.style.opacity = el.classList.contains('is-flying') ? '' : p <= 3 ? 1 : 0
    })
    els[order[0]].classList.add('is-top')
    order.slice(1).forEach((idx) => els[idx].classList.remove('is-top'))
  }

  // La leyenda (y quien escuche onChange) siempre corresponde a la carta de arriba.
  const sync = () => {
    const item = items[order[0]]
    caption.classList.add('is-out')
    onChange?.(item)
    setTimeout(() => {
      caption.textContent = item.text
      caption.classList.remove('is-out')
    }, 140)
  }

  // La carta de arriba sale volando hacia un lado y pasa al fondo de la pila.
  const advance = (dir = Math.random() < 0.5 ? -1 : 1) => {
    if (busy) return
    busy = true
    const top = els[order[0]]
    top.style.transform = ''
    top.style.transition = ''
    top.style.setProperty('--dir', dir)
    top.classList.add('is-flying')
    order.push(order.shift())
    render()
    sync()
    setTimeout(
      () => {
        top.style.transition = 'none'
        top.classList.remove('is-flying')
        render()
        void top.offsetWidth
        top.style.transition = ''
        busy = false
      },
      reduced ? 0 : 480,
    )
  }

  let timer
  const restart = () => {
    clearInterval(timer)
    if (!reduced) timer = setInterval(() => advance(), interval)
  }

  // Arrastrar la carta de arriba: al soltar lejos, sale volando.
  let startX = null
  let dx = 0
  stack.addEventListener('pointerdown', (e) => {
    if (busy) return
    startX = e.clientX
    dx = 0
    stack.setPointerCapture(e.pointerId)
    clearInterval(timer)
  })
  stack.addEventListener('pointermove', (e) => {
    if (startX === null) return
    dx = e.clientX - startX
    const top = els[order[0]]
    top.style.transition = 'none'
    top.style.transform = `translateX(${dx}px) rotate(${dx * 0.06}deg)`
  })
  const release = () => {
    if (startX === null) return
    const moved = dx
    startX = null
    const top = els[order[0]]
    top.style.transition = ''
    if (Math.abs(moved) > 80) {
      advance(Math.sign(moved)) // solo cambia si el usuario la desliza
    } else {
      top.style.transform = '' // vuelve a su sitio
    }
    restart()
  }
  stack.addEventListener('pointerup', release)
  stack.addEventListener('pointercancel', release)

  // Pausa el avance automático al pasar el mouse.
  const area = root.querySelector('.stack-wrap')
  area.addEventListener('mouseenter', () => clearInterval(timer))
  area.addEventListener('mouseleave', restart)

  onCleanup(() => clearInterval(timer))
  render()
  restart()
}
