import './onboarding.css'
import { t, getLang } from '@/core/i18n.js'
import { roleArt } from '@/shared/assets/illustrations/index.js'

// Onboarding de la app móvil: 3 vistas que se deslizan (scroll-snap) y, al final, crear cuenta o entrar.
// init recibe el `scope` de limpieza y { onFinish(kind) } con kind = 'register' | 'login', o null al tocar "Saltar".
const SLIDES = [
  { id: 'talk', art: 'viajes' },
  { id: 'report', art: 'entrevistador' },
  { id: 'daily', art: 'vida-diaria' },
]

let current = 0 // se conserva al cambiar de idioma

export function renderOnboarding() {
  const lang = getLang()
  const pill = (code) =>
    `<button type="button" data-lang="${code}" aria-pressed="${lang === code}" ${lang === code ? 'class="is-on"' : ''}>${code.toUpperCase()}</button>`
  const slides = SLIDES.map(
    (s, i) => `
      <section class="onb__slide" data-i="${i}" aria-roledescription="slide"
        aria-label="${t('onboarding.step', { n: i + 1, total: SLIDES.length })}">
        <div class="onb__art onb__art--${i}"><img src="${roleArt(s.art)}" alt="" /></div>
        <h2 class="onb__title">${t(`onboarding.slides.${s.id}.title`)}</h2>
        <p class="onb__text">${t(`onboarding.slides.${s.id}.text`)}</p>
      </section>`,
  ).join('')
  const dots = SLIDES.map((_, i) => `<span class="onb__dot" data-dot="${i}"></span>`).join('')

  return `
    <div class="onb">
      <header class="onb__bar">
        <div class="onb__langs" role="group" aria-label="${t('onboarding.language')}">${pill('es')}${pill('en')}</div>
        <button class="onb__skip" type="button" data-onb="skip">${t('onboarding.skip')}</button>
      </header>
      <div class="onb__track" tabindex="0">${slides}</div>
      <footer class="onb__foot">
        <div class="onb__dots" aria-hidden="true">${dots}</div>
        <div class="onb__actions" data-actions></div>
      </footer>
    </div>`
}

export function initOnboarding(root, scope, { onFinish }) {
  const track = root.querySelector('.onb__track')
  const actions = root.querySelector('[data-actions]')
  const last = SLIDES.length - 1

  const paint = () => {
    root.querySelectorAll('[data-dot]').forEach((d) => d.classList.toggle('is-on', Number(d.dataset.dot) === current))
    root.querySelector('[data-onb="skip"]').hidden = current === last
    actions.innerHTML =
      current === last
        ? `<button class="btn btn--primary" type="button" data-onb="register">${t('onboarding.register')}</button>
           <button class="btn btn--ghost" type="button" data-onb="login">${t('onboarding.login')}</button>`
        : `<button class="btn btn--primary" type="button" data-onb="next">${t('onboarding.next')}</button>`
  }
  // Mientras el botón anima el desplazamiento, el scroll no cuenta como "deslizó con el dedo"
  let animatingUntil = 0
  const goTo = (i, smooth = true) => {
    current = Math.max(0, Math.min(last, i))
    animatingUntil = smooth ? Date.now() + 700 : 0
    track.scrollTo({ left: current * track.clientWidth, behavior: smooth ? 'smooth' : 'instant' })
    paint()
  }

  // Deslizar con el dedo: la vista que queda centrada al terminar es la actual
  const settle = () => {
    if (Date.now() < animatingUntil) return
    const i = Math.round(track.scrollLeft / track.clientWidth)
    if (i !== current) {
      current = i
      paint()
    }
  }
  let timer = 0
  if ('onscrollend' in window) scope.listen(track, 'scrollend', settle)
  else {
    scope.listen(track, 'scroll', () => {
      clearTimeout(timer)
      timer = setTimeout(settle, 120)
    })
    scope.onCleanup(() => clearTimeout(timer))
  }

  scope.listen(root, 'click', (e) => {
    const action = e.target.closest('[data-onb]')?.dataset.onb
    if (action === 'next') goTo(current + 1)
    else if (action === 'skip') onFinish(null)
    else if (action === 'register' || action === 'login') onFinish(action)
  })
  scope.listen(track, 'keydown', (e) => {
    if (e.key === 'ArrowRight') goTo(current + 1)
    if (e.key === 'ArrowLeft') goTo(current - 1)
  })

  goTo(current, false)
}
