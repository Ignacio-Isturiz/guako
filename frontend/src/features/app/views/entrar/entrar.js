import './entrar.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t } from '@/core/i18n.js'
import { isNative } from '@/core/native.js'

// 1. Entrar: acceso a la cuenta (el formulario es el modal de login/registro).
// En la app móvil no hay landing, así que no se muestra "Volver a la página principal".
export default {
  head: () => ({ eyebrow: '', title: t('app.entrar.title') }),
  render: () => `
    <section class="gate">
      <div class="gate__card">
        <img class="gate__mascot" src="${logo}" alt="" width="96" height="96" />
        <h1>${t('app.entrar.title')}</h1>
        <p>${t('app.entrar.text')}</p>
        <div class="gate__buttons">
          <button class="btn btn--primary" type="button" data-auth="login">${t('app.entrar.login')}</button>
          <button class="btn btn--outline" type="button" data-auth="register">${t('app.entrar.register')}</button>
        </div>
        ${isNative ? '' : `<button class="link" type="button" data-nav="/">${t('app.nav.backHome')}</button>`}
      </div>
    </section>`,
}
