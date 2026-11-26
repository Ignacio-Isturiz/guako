import './flag-reply.css'
import { t } from '@/core/i18n.js'
import { createModal } from '@/shared/components/modal/modal.js'
import { flagReply, errorText } from '@/features/app/data/sessions-api.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { toast } from '@/features/app/components/toast/toast.js'

// Reportar una respuesta de Guako (ofensiva, dañina, incorrecta…). Google Play lo exige a las apps
// con IA generativa y Apple también lo revisa. Lo usan la conversación en vivo y la revisión.
//   flagButton(turnNumber) → HTML del botón (va dentro de la burbuja de Guako)
//   openFlagReply({ sessionId, turnNumber }) → abre el diálogo y envía el reporte
const REASONS = ['offensive', 'harmful', 'wrong', 'other']
const MAX_COMMENT = 500

export const flagButton = (turnNumber) =>
  `<button type="button" class="flag-btn" data-flag="${Number(turnNumber)}" aria-label="${t('app.flag.button')}" title="${t('app.flag.button')}">${icon('flag', 15)}</button>`

let modal = null

export function openFlagReply({ sessionId, turnNumber }) {
  if (!modal) {
    modal = createModal({ className: 'modal--flag' })
    modal.labelledBy('flagTitle')
  }
  const option = (r, i) => `
    <label class="flag__option">
      <input type="radio" name="flagReason" value="${r}" ${i === 0 ? 'checked' : ''} />
      <span>${t(`app.flag.reasons.${r}`)}</span>
    </label>`

  modal.body.innerHTML = `
    <button class="modal__close" type="button" data-close aria-label="${t('app.flag.cancel')}">×</button>
    <h2 class="modal__title" id="flagTitle">${t('app.flag.title')}</h2>
    <p class="modal__sub">${t('app.flag.sub')}</p>
    <form class="flag__form">
      <fieldset class="flag__reasons">
        <legend class="flag__legend">${t('app.flag.why')}</legend>
        ${REASONS.map(option).join('')}
      </fieldset>
      <label class="flag__label" for="flagComment">${t('app.flag.comment')}</label>
      <textarea class="flag__comment" id="flagComment" rows="3" maxlength="${MAX_COMMENT}"></textarea>
      <div class="flag__actions">
        <button class="btn btn--outline" type="button" data-close>${t('app.flag.cancel')}</button>
        <button class="btn btn--primary" type="submit">${t('app.flag.send')}</button>
      </div>
    </form>`

  const form = modal.body.querySelector('form')
  form.addEventListener('submit', async (e) => {
    e.preventDefault()
    const send = form.querySelector('[type=submit]')
    send.disabled = true
    try {
      await flagReply(sessionId, turnNumber, {
        reason: new FormData(form).get('flagReason'),
        comment: form.querySelector('textarea').value.trim() || null,
      })
      modal.close()
      toast(t('app.flag.thanks'))
    } catch (err) {
      send.disabled = false
      toast(errorText(err))
    }
  })
  modal.open()
  form.querySelector('input:checked').focus()
}
