import './ajustes.css'
import { t, getLang } from '@/core/i18n.js'
import { navigate } from '@/core/router.js'
import { settings, setSetting, exportData, deleteAccount } from '@/features/app/data/store.js'
import { loadConsents, readAudioConsent, writeAudioConsent } from '@/features/app/data/consent.js'
import { confirmDialog } from '@/features/app/components/confirm-dialog/confirm-dialog.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { toast } from '@/features/app/components/toast/toast.js'
import { esc } from '@/features/app/utils/html.js'
import {
  remindersAvailable,
  reminderHour,
  setReminderHour,
  notificationPermission,
  askNotificationPermission,
} from '@/features/app/services/reminders.js'

const radio = (name, value, current, title, body) => `
  <label class="opt ${current === value ? 'is-on' : ''}">
    <input type="radio" name="${name}" value="${value}" ${current === value ? 'checked' : ''} />
    <span class="opt__dot" aria-hidden="true"></span>
    <span class="opt__text"><strong>${title}</strong><small>${body}</small></span>
  </label>`

// Recordatorio diario de racha: solo existe en la app móvil y en la web instalada, y siempre está activo. Aquí se elige la hora
// y se ve si el teléfono deja mostrar notificaciones (el estado se pinta en init, es asíncrono).
const HOURS = [7, 8, 9, 12, 13, 18, 19, 20, 21, 22]
const reminderCard = () => `
  <section class="card">
    <h2 class="card__title">${t('app.settings.reminderTitle')}</h2>
    <p class="card__sub">${t('app.settings.reminderText')}</p>
    <label class="reminder__hour">${t('app.settings.reminderAt')}
      <select id="reminderHour">${HOURS.map((h) => `<option value="${h}" ${h === reminderHour() ? 'selected' : ''}>${String(h).padStart(2, '0')}:00</option>`).join('')}</select>
    </label>
    <p class="reminder__status" id="reminderStatus" aria-live="polite"></p>
  </section>`

// 10. Ajustes: idioma de las explicaciones, qué se hace con los audios, exportar y borrar
export default {
  head: () => ({ eyebrow: t('app.settings.eyebrow'), title: t('app.settings.title') }),
  render() {
    const s = settings()
    const lang = getLang()
    return `
      <div class="settings">
        <section class="card">
          <h2 class="card__title">${t('app.settings.explainTitle')}</h2>
          <p class="card__sub">${t('app.settings.explainText')}</p>
          <div class="opts opts--3">
            ${['es', 'en', 'mix'].map((k) => radio('explain', k, s.explain, t(`app.settings.explain.${k}.name`), esc(t(`app.settings.explain.${k}.ex`)))).join('')}
          </div>
        </section>

        <section class="card row">
          <div>
            <h2 class="card__title">${t('app.settings.consentTitle')}</h2>
            <p class="card__sub">${t('app.settings.consentText')}</p>
            <p class="card__sub"><button type="button" class="link" data-legal="privacy">${t('app.settings.consentMore')}</button></p>
          </div>
          <label class="switch">
            <input type="checkbox" id="audioConsent" ${readAudioConsent() === true ? 'checked' : ''} />
            <span class="switch__track" aria-hidden="true"></span>
            <span class="switch__text" id="consentState" aria-live="polite">${t(readAudioConsent() === true ? 'app.settings.consentOn' : 'app.settings.consentOff')}</span>
          </label>
        </section>

        <section class="card">
          <h2 class="card__title">${t('app.settings.audioTitle')}</h2>
          <p class="card__sub">${t('app.settings.audioText')}</p>
          <div class="opts">
            ${['delete', '30d', 'keep'].map((k) => radio('audio', k, s.audio, t(`app.settings.audio.${k}.name`), t(`app.settings.audio.${k}.hint`))).join('')}
          </div>
        </section>

        <section class="card row">
          <div>
            <h2 class="card__title">${t('app.settings.soundTitle')}</h2>
            <p class="card__sub">${t('app.settings.soundText')}</p>
          </div>
          <label class="switch">
            <input type="checkbox" id="sound" ${s.sound ? 'checked' : ''} />
            <span class="switch__track" aria-hidden="true"></span>
            <span class="switch__text" id="soundText">${t(s.sound ? 'app.settings.soundOn' : 'app.settings.soundOff')}</span>
          </label>
        </section>

        ${remindersAvailable ? reminderCard() : ''}

        <section class="card row">
          <div>
            <h2 class="card__title">${t('app.settings.interface')}</h2>
            <p class="card__sub">${t('app.settings.interfaceText')}</p>
          </div>
          <div class="lang lang--lg" role="group">
            <button type="button" data-lang="es" aria-pressed="${lang === 'es'}" ${lang === 'es' ? 'class="is-on"' : ''}>ES</button>
            <button type="button" data-lang="en" aria-pressed="${lang === 'en'}" ${lang === 'en' ? 'class="is-on"' : ''}>EN</button>
          </div>
        </section>

        <section class="card row">
          <div>
            <h2 class="card__title">${t('app.settings.exportTitle')}</h2>
            <p class="card__sub">${t('app.settings.exportText')}</p>
          </div>
          <button class="btn btn--navy" type="button" id="export">${icon('download', 18)}${t('app.settings.exportBtn')}</button>
        </section>

        <section class="card row">
          <div>
            <h2 class="card__title">${t('app.settings.legal')}</h2>
          </div>
          <div class="row__btns">
            <button class="btn btn--outline btn--sm" type="button" data-legal="terms">${t('footer.terms')}</button>
            <button class="btn btn--outline btn--sm" type="button" data-legal="privacy">${t('footer.privacy')}</button>
          </div>
        </section>

        <section class="card danger row">
          <div>
            <h2 class="card__title">${t('app.settings.deleteTitle')}</h2>
            <p class="card__sub">${t('app.settings.deleteText')}</p>
          </div>
          <button class="btn btn--danger" type="button" id="delete">${icon('trash', 18)}${t('app.settings.deleteBtn')}</button>
        </section>
      </div>`
  },

  init(root, _p, scope) {
    const paintConsent = () => {
      const box = root.querySelector('#audioConsent')
      if (!box) return
      box.checked = readAudioConsent() === true
      root.querySelector('#consentState').textContent = t(box.checked ? 'app.settings.consentOn' : 'app.settings.consentOff')
    }
    loadConsents({ fresh: true }).then(() => root.isConnected && paintConsent())

    // Recordatorio: ¿el teléfono deja mostrar notificaciones? Si no, botón para pedirlas otra vez
    const paintReminder = async () => {
      const box = root.querySelector('#reminderStatus')
      if (!box) return
      const state = await notificationPermission()
      if (!root.isConnected) return
      box.innerHTML =
        state === 'granted'
          ? `${icon('check', 16)} ${t('app.settings.reminderPermOn')}`
          : `${t('app.settings.reminderPermOff')} <button type="button" class="btn btn--navy btn--sm" id="reminderAsk">${t('app.settings.reminderEnable')}</button>`
      box.classList.toggle('is-off', state !== 'granted')
    }
    if (remindersAvailable) paintReminder()
    scope.listen(root, 'click', async (e) => {
      if (!e.target.closest('#reminderAsk')) return
      if (!(await askNotificationPermission())) toast(t('app.settings.reminderDenied'))
      paintReminder()
    })

    scope.listen(root, 'change', (e) => {
      const el = e.target
      if (el.matches('input[type=radio]')) {
        setSetting(el.name, el.value)
        root.querySelectorAll(`input[name="${el.name}"]`).forEach((r) => r.closest('.opt').classList.toggle('is-on', r.checked))
        toast(t('app.settings.saved'))
      } else if (el.id === 'audioConsent') {
        // Se guarda en el servidor (es la prueba de la autorización); si falla, el interruptor vuelve atrás.
        const on = el.checked
        el.disabled = true
        writeAudioConsent(on)
          .then(() => toast(t('app.settings.saved')))
          .catch(() => {
            el.checked = !on
            toast(t('app.settings.consentError'))
          })
          .finally(() => {
            el.disabled = false
            paintConsent()
          })
      } else if (el.id === 'reminderHour') {
        setReminderHour(Number(el.value)).then(() => toast(t('app.settings.saved')))
      } else if (el.id === 'sound') {
        setSetting('sound', el.checked)
        root.querySelector('#soundText').textContent = t(el.checked ? 'app.settings.soundOn' : 'app.settings.soundOff')
        toast(t('app.settings.saved'))
      }
    })

    scope.listen(root.querySelector('#export'), 'click', () => {
      const url = URL.createObjectURL(new Blob([exportData()], { type: 'application/json' }))
      const a = document.createElement('a')
      a.href = url
      a.download = 'guako-mis-datos.json'
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      toast(t('app.settings.exported'))
    })

    scope.listen(root.querySelector('#delete'), 'click', async () => {
      const ok = await confirmDialog({
        title: t('app.settings.deleteConfirmTitle'),
        text: t('app.settings.deleteConfirmText', { word: t('app.settings.deleteWord') }),
        yes: t('app.settings.deleteYes'),
        no: t('app.settings.cancel'),
        danger: true,
        requireWord: t('app.settings.deleteWord'),
      })
      if (!ok) return
      const button = root.querySelector('#delete')
      button.disabled = true
      try {
        await deleteAccount()
        navigate('/')
      } catch {
        button.disabled = false
        toast(t('app.settings.deleteError'))
      }
    })
  },
}
