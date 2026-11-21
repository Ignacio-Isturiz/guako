import './level-test.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t } from '@/core/i18n.js'
import { createModal } from '@/shared/components/modal/modal.js'
import { LEVELS, LEVEL_TEST } from '@/features/app/data/seed.js'
import { esc } from '@/features/app/utils/html.js'

// Prueba corta de nivel (modal de 5 preguntas). onUse(nivel) se llama si el usuario acepta el nivel sugerido.
let testModal = null
export function openLevelTest(onUse) {
  if (!testModal) {
    testModal = createModal({ className: 'modal--test' })
    testModal.labelledBy('testTitle')
  }
  const m = testModal
  let i = 0
  let correct = 0

  const question = () => {
    const q = LEVEL_TEST[i]
    m.body.innerHTML = `
      <button class="modal__close" type="button" data-close aria-label="${t('app.test.close')}">×</button>
      <h2 class="modal__title" id="testTitle">${t('app.test.title')}</h2>
      <p class="modal__small">${t('app.test.progress', { n: i + 1, total: LEVEL_TEST.length })}</p>
      <div class="meter-bar" aria-hidden="true"><i style="width:${(i / LEVEL_TEST.length) * 100}%"></i></div>
      <p class="test__q">${esc(q.q)}</p>
      <p class="test__es">${esc(q.es)}</p>
      <div class="test__options" role="group" aria-label="${esc(q.q)}">
        ${q.options.map((o, k) => `<button type="button" class="test__opt" data-opt="${k}">${esc(o)}</button>`).join('')}
      </div>`
    m.body.querySelectorAll('[data-opt]').forEach((b) =>
      b.addEventListener('click', () => {
        const k = Number(b.dataset.opt)
        if (k === q.answer) correct++
        b.classList.add(k === q.answer ? 'is-right' : 'is-wrong')
        m.body.querySelector(`[data-opt="${q.answer}"]`).classList.add('is-right')
        m.body.querySelectorAll('[data-opt]').forEach((x) => (x.disabled = true))
        setTimeout(() => (++i < LEVEL_TEST.length ? question() : result()), 650)
      }),
    )
    m.body.querySelector('[data-opt]')?.focus()
  }

  const result = () => {
    const lvl = LEVELS[Math.min(LEVELS.length - 1, Math.max(0, correct - 1))]
    m.body.innerHTML = `
      <button class="modal__close" type="button" data-close aria-label="${t('app.test.close')}">×</button>
      <img class="modal__mascot" src="${logo}" alt="" width="64" height="64" />
      <h2 class="modal__title" id="testTitle">${t('app.test.resultTitle', { level: lvl })}</h2>
      <p class="modal__sub">${t('app.test.resultText', { n: correct, total: LEVEL_TEST.length })}</p>
      <div class="test__actions">
        <button class="btn btn--primary btn--block" type="button" data-use data-autofocus>${t('app.test.use')}</button>
        <button class="link" type="button" data-retry>${t('app.test.retry')}</button>
      </div>`
    m.body.querySelector('[data-use]').addEventListener('click', () => {
      onUse(lvl)
      m.close()
    })
    m.body.querySelector('[data-retry]').addEventListener('click', () => {
      i = 0
      correct = 0
      question()
    })
    m.body.querySelector('[data-use]').focus()
  }

  m.body.innerHTML = `
    <button class="modal__close" type="button" data-close aria-label="${t('app.test.close')}">×</button>
    <img class="modal__mascot" src="${logo}" alt="" width="64" height="64" />
    <h2 class="modal__title" id="testTitle">${t('app.test.title')}</h2>
    <p class="modal__sub">${t('app.test.intro')}</p>
    <button class="btn btn--primary btn--block test__go" type="button" data-go>${t('app.test.next')}</button>`
  m.body.querySelector('[data-go]').addEventListener('click', question)
  m.open()
  m.body.querySelector('[data-go]').focus()
}
