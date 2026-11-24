import './preparar.css'
import { t } from '@/core/i18n.js'
import { navigate } from '@/core/router.js'
import { TOPICS, LEVELS } from '@/features/app/data/seed.js'
import { level as savedLevel } from '@/features/app/data/store.js'
import { readSetup, writeSetup } from '@/features/app/data/setup.js'
import { readAudioConsent } from '@/features/app/data/consent.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { roleArt as art } from '@/shared/assets/illustrations/index.js'
import { openLevelTest } from './level-test.js'

const ROLE_MAX = 200 // el backend acepta hasta 200 caracteres

/* ---------- Pantalla ---------- */
const topicCard = (tp) => `
  <button type="button" class="topic" data-topic="${tp.id}" aria-pressed="false">
    <span class="topic__art"><img src="${art(tp.art)}" alt="" width="200" height="200" /></span>
    <span class="topic__check" aria-hidden="true">${icon('check', 16)}</span>
    <strong>${t(`app.topics.${tp.id}.name`)}</strong>
    <small>${t(`app.topics.${tp.id}.hint`)}</small>
  </button>`

const levelChip = (l) => `
  <button type="button" class="level" data-level="${l}" aria-pressed="false">
    <b>${l}</b><strong>${t(`app.levels.${l}.name`)}</strong><small>${t(`app.levels.${l}.hint`)}</small>
    <em class="level__sug" hidden>${t('app.prepare.suggested')}</em>
  </button>`

// 3. Preparar conversación: tema, nivel y (si no lo sabe) prueba corta
export default {
  head: () => ({ eyebrow: t('app.prepare.eyebrow'), title: t('app.prepare.title') }),
  render: () => `
    <div class="setup">
      <div class="setup__main">
        <section class="card">
          <h2 class="card__title">${t('app.prepare.topicTitle')}</h2>
          <div class="topics">
            ${TOPICS.map(topicCard).join('')}
            <button type="button" class="topic topic--custom" data-topic="custom" aria-pressed="false">
              <span class="topic__art topic__art--icon">${icon('pencil', 40)}</span>
              <span class="topic__check" aria-hidden="true">${icon('check', 16)}</span>
              <strong>${t('app.topics.custom.name')}</strong>
              <small>${t('app.topics.custom.hint')}</small>
            </button>
          </div>
          <label class="custom" id="customWrap" hidden>
            <span>${t('app.prepare.customLabel')}</span>
            <input type="text" id="customTopic" maxlength="60" placeholder="${esc(t('app.topics.custom.placeholder'))}" />
          </label>
        </section>

        <section class="card">
          <h2 class="card__title">${t('app.prepare.roleTitle')}</h2>
          <p class="card__sub">${t('app.prepare.roleText')}</p>
          <label class="custom role">
            <span>${t('app.prepare.roleLabel')}</span>
            <input type="text" id="roleInput" maxlength="${ROLE_MAX}" placeholder="${esc(t('app.prepare.rolePlaceholder'))}" />
          </label>
          <div class="role__examples" role="group" aria-label="${t('app.prepare.roleExamplesLabel')}">
            ${t('app.prepare.roleExamples').map((r) => `<button type="button" class="chip role__chip" data-role="${esc(r)}">${esc(r)}</button>`).join('')}
          </div>
        </section>

        <section class="card">
          <h2 class="card__title">${t('app.prepare.levelTitle')}</h2>
          <div class="levels">
            ${LEVELS.map(levelChip).join('')}
            <button type="button" class="level level--test" data-test>
              ${icon('bulb', 22)}<strong>${t('app.prepare.levelUnknown')}</strong><small>${t('app.prepare.levelUnknownText')}</small>
            </button>
          </div>
        </section>
      </div>

      <aside class="setup__aside">
        <div class="card summary">
          <h2 class="card__eyebrow">${t('app.prepare.summary')}</h2>
          <dl>
            <div><dt>${t('app.prepare.summaryTopic')}</dt><dd id="sumTopic"></dd></div>
            <div><dt>${t('app.prepare.summaryRole')}</dt><dd id="sumRole"></dd></div>
            <div><dt>${t('app.prepare.summaryLevel')}</dt><dd id="sumLevel"></dd></div>
            <div><dt>${t('app.prepare.summaryAudio')}</dt><dd><span id="sumAudio"></span> · <button type="button" class="link" data-nav="/app/ajustes">${t('app.prepare.consentChange')}</button></dd></div>
          </dl>
          <button class="btn btn--primary btn--block btn--lg" type="button" id="startBtn">${icon('mic', 22)}${t('app.prepare.start')}</button>
          <p class="summary__note" id="startNote">${t('app.prepare.missing')}</p>
          <p class="summary__tip">${icon('bulb', 16)}<span>${t('app.prepare.tip')}</span></p>
        </div>
      </aside>
    </div>`,

  init(root, _p, scope) {
    const draft = readSetup() || {}
    const state = { topicId: draft.topicId || '', custom: draft.custom || '', level: draft.level || savedLevel() || '', suggested: draft.suggested || '', role: draft.role || '' }
    const customInput = root.querySelector('#customTopic')
    const roleInput = root.querySelector('#roleInput')
    customInput.value = state.custom
    roleInput.value = state.role

    const ready = () => state.topicId && state.level && (state.topicId !== 'custom' || state.custom.trim())
    const paint = () => {
      root.querySelectorAll('[data-topic]').forEach((b) => {
        const on = b.dataset.topic === state.topicId
        b.classList.toggle('is-on', on)
        b.setAttribute('aria-pressed', String(on))
      })
      root.querySelectorAll('[data-level]').forEach((b) => {
        const on = b.dataset.level === state.level
        b.classList.toggle('is-on', on)
        b.setAttribute('aria-pressed', String(on))
        b.querySelector('.level__sug').hidden = !(state.suggested && b.dataset.level === state.suggested)
      })
      root.querySelector('#customWrap').hidden = state.topicId !== 'custom'
      root.querySelector('#sumTopic').textContent = state.topicId
        ? state.topicId === 'custom'
          ? state.custom.trim() || t('app.topics.custom.name')
          : t(`app.topics.${state.topicId}.name`)
        : t('app.prepare.summaryEmpty')
      root.querySelector('#sumRole').textContent = state.role.trim() || t('app.prepare.roleNone')
      root.querySelector('#sumLevel').textContent = state.level ? `${state.level} · ${t(`app.levels.${state.level}.name`)}` : t('app.prepare.summaryEmpty')
      root.querySelector('#sumAudio').textContent = t(readAudioConsent() ? 'app.prepare.consentOn' : 'app.prepare.consentOff')
      const ok = !!ready()
      root.querySelector('#startBtn').disabled = !ok
      root.querySelector('#startNote').hidden = ok
      writeSetup(state)
    }

    scope.listen(root, 'click', (e) => {
      const topic = e.target.closest('[data-topic]')
      if (topic) {
        state.topicId = topic.dataset.topic
        paint()
        if (state.topicId === 'custom') customInput.focus()
        return
      }
      const example = e.target.closest('[data-role]')
      if (example) {
        state.role = example.dataset.role
        roleInput.value = state.role
        paint()
        return
      }
      const lvl = e.target.closest('[data-level]')
      if (lvl) {
        state.level = lvl.dataset.level
        paint()
        return
      }
      if (e.target.closest('[data-test]')) {
        openLevelTest((l) => {
          state.level = l
          state.suggested = l
          paint()
        })
        return
      }
      if (e.target.closest('#startBtn') && ready()) {
        writeSetup(state)
        navigate('/app/conversacion')
      }
    })
    scope.listen(customInput, 'input', () => {
      state.custom = customInput.value
      paint()
    })
    scope.listen(roleInput, 'input', () => {
      state.role = roleInput.value
      paint()
    })
    paint()
  },
}
