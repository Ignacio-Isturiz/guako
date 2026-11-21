// Modal accesible reutilizable: atrapa el foco, se cierra con Esc o al tocar el fondo,
// bloquea el scroll de la página y devuelve el foco al cerrar.
// Los modales se apilan (por ejemplo, términos abiertos desde el login).
import './modal.css'
const stack = []
let locks = 0

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])'

document.addEventListener('keydown', (e) => {
  const top = stack[stack.length - 1]
  if (!top) return
  if (e.key === 'Escape') {
    e.preventDefault()
    top.close()
    return
  }
  if (e.key === 'Tab') {
    const items = [...top.card.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null)
    if (!items.length) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    } else if (!top.card.contains(document.activeElement)) {
      e.preventDefault()
      first.focus()
    }
  }
})

export function createModal({ className = '', onClose } = {}) {
  const root = document.createElement('div')
  root.className = `modal ${className}`
  root.hidden = true
  root.innerHTML = `
    <div class="modal__backdrop" data-close></div>
    <div class="modal__card" role="dialog" aria-modal="true" tabindex="-1">
      <div class="modal__body"></div>
    </div>`
  document.body.appendChild(root)

  const card = root.querySelector('.modal__card')
  const body = root.querySelector('.modal__body')
  let lastFocus = null
  let hideTimer = 0

  const api = {
    root,
    card,
    body,
    get isOpen() {
      return !root.hidden && root.classList.contains('is-open')
    },
    labelledBy(id) {
      card.setAttribute('aria-labelledby', id)
    },
    open() {
      if (api.isOpen) return
      clearTimeout(hideTimer)
      lastFocus = document.activeElement
      root.hidden = false
      void root.offsetWidth // fuerza el estilo inicial para que la entrada se anime
      root.classList.add('is-open')
      stack.push(api)
      if (locks++ === 0) document.documentElement.classList.add('is-locked')
    },
    close() {
      if (!api.isOpen) return
      root.classList.remove('is-open')
      const i = stack.indexOf(api)
      if (i >= 0) stack.splice(i, 1)
      if (--locks === 0) document.documentElement.classList.remove('is-locked')
      hideTimer = setTimeout(() => (root.hidden = true), 220)
      lastFocus?.focus?.()
      onClose?.()
    },
  }

  root.addEventListener('click', (e) => {
    if (e.target.closest('[data-close]')) api.close()
  })
  return api
}
