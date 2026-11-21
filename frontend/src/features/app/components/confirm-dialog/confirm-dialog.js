import './confirm-dialog.css'
import { createModal } from '@/shared/components/modal/modal.js'
import { esc } from '@/features/app/utils/html.js'

// Diálogo de confirmación reutilizable. Devuelve una promesa: true si confirma, false si cancela.
// Con `requireWord` el usuario debe escribir esa palabra para habilitar el botón (acciones peligrosas).
let modal = null
let pending = null

export function confirmDialog({ title, text, yes, no, danger = false, requireWord = '', hint = '' }) {
  if (!modal) {
    modal = createModal({
      className: 'modal--confirm',
      onClose: () => {
        pending?.(false)
        pending = null
      },
    })
    modal.labelledBy('confirmTitle')
  }
  return new Promise((resolve) => {
    modal.body.innerHTML = `
      <button class="modal__close" type="button" data-close aria-label="${esc(no)}">×</button>
      <h2 class="modal__title" id="confirmTitle">${esc(title)}</h2>
      <p class="modal__sub">${esc(text)}</p>
      ${requireWord ? `<input class="confirm__input" type="text" autocomplete="off" aria-label="${esc(hint || requireWord)}" placeholder="${esc(requireWord)}" />` : ''}
      <div class="confirm__actions">
        <button class="btn btn--outline" type="button" data-no>${esc(no)}</button>
        <button class="btn ${danger ? 'btn--danger' : 'btn--primary'}" type="button" data-yes ${requireWord ? 'disabled' : ''}>${esc(yes)}</button>
      </div>`
    const yesBtn = modal.body.querySelector('[data-yes]')
    const input = modal.body.querySelector('.confirm__input')
    const settle = (value) => {
      pending = null
      modal.close()
      resolve(value)
    }
    pending = resolve
    yesBtn.addEventListener('click', () => settle(true))
    modal.body.querySelector('[data-no]').addEventListener('click', () => settle(false))
    if (input) input.addEventListener('input', () => (yesBtn.disabled = input.value.trim().toUpperCase() !== requireWord.toUpperCase()))
    modal.open()
    ;(input || modal.body.querySelector('[data-no]')).focus()
  })
}
