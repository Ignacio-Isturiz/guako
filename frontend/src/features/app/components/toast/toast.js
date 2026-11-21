import './toast.css'

// Mensaje corto de aviso que desaparece solo
export function toast(message) {
  let el = document.querySelector('.toast')
  if (!el) {
    el = document.createElement('div')
    el.className = 'toast'
    el.setAttribute('role', 'status')
    document.body.appendChild(el)
  }
  el.textContent = message
  el.classList.add('is-on')
  clearTimeout(toast.t)
  toast.t = setTimeout(() => el.classList.remove('is-on'), 2400)
}
