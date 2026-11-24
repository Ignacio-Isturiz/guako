// Informe real: se pide al backend (GET /api/sessions/{id}/report) en lugar de usar datos de ejemplo.
// Solo se pintan puntajes que el backend calculó: lo que aún no existe sale como "pendiente".
import { t } from '@/core/i18n.js'
import { getReport, errorText } from '@/features/app/data/sessions-api.js'
import { speak, canSpeak } from '@/features/app/services/tts.js'
import { toast } from '@/features/app/components/toast/toast.js'
import { createWordPractice } from './word-practice.js'
import { ring } from '@/features/app/components/ring/ring.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { aspectName, ASPECT_COLOR, toneText } from '@/features/app/utils/scores.js'

// Aspecto de la interfaz → campo del informe del backend
const ASPECT_FIELD = { pron: 'pronunciation', gram: 'grammar', fluency: 'fluency', clarity: 'communication', listening: 'listening' }
const ASPECT_ORDER = ['pron', 'gram', 'fluency', 'clarity', 'listening']

const loading = () => `
  <div class="card overall">
    <div class="ring ring--ghost" style="--size:96px"><span>${icon('spinner', 30)}</span></div>
    <p>${t('app.report.analyzing')}</p>
  </div>`

const failed = (err) => `
  <div class="card empty">
    <p role="alert">${esc(errorText(err))}</p>
    <button class="btn btn--primary" type="button" data-retry>${t('app.report.live.retry')}</button>
  </div>`

function scoreCard(a, dim) {
  const score = dim.score
  const pending = dim.status === 'pending'
  const sub = score != null ? toneText(score, a) : t(pending ? 'app.report.live.pending' : 'app.report.live.noData')
  const visual =
    score != null
      ? ring(score, { size: 84, stroke: 9, color: ASPECT_COLOR[a] })
      : `<div class="ring ring--ghost" style="--size:84px"><span>${icon(pending ? 'clock' : 'check', 22)}</span></div>`
  return `
    <div class="score ${score != null ? '' : 'is-pending'}">
      ${visual}
      <strong>${aspectName(a)}</strong>
      <small>${sub}</small>
    </div>`
}

const errorsCard = (grammar) => {
  if (!grammar.errors.length) return ''
  return `
    <section class="card">
      <h2 class="card__title">${t('app.report.errorsTitle')}</h2>
      <p class="card__sub">${t('app.report.live.errorsText', { n: grammar.errors.length })}</p>
      <ol class="errors">
        ${grammar.errors
          .map(
            (e, i) => `<li><span class="errors__n">${i + 1}</span><div>
              <strong>${esc(e.original)} → ${esc(e.correction)}</strong>
              <p>${esc(e.error_type)}. ${esc(e.explanation)}</p>
            </div></li>`,
          )
          .join('')}
      </ol>
    </section>`
}

const fluencyCard = (f) =>
  f.status !== 'ok'
    ? ''
    : `
    <section class="card">
      <h2 class="card__title">${t('app.report.live.fluencyTitle')}</h2>
      <ul class="status">
        <li class="status__item"><span><strong>${f.words_per_minute}</strong><small>${t('app.report.live.wpm')}</small></span></li>
        <li class="status__item"><span><strong>${f.long_pauses}</strong><small>${t('app.report.live.pauses')}</small></span></li>
        <li class="status__item"><span><strong>${f.filler_words}</strong><small>${t('app.report.live.fillers')}</small></span></li>
      </ul>
    </section>`

// Pronunciación. El texto sale de claves del frontend (ES/EN) a partir de `status`, `reason` y los
// contadores del backend, no de sus notas (solo vienen en español).
// REGLA DE JUSTICIA: nunca se habla de "acento incorrecto" ni "pronunciaste mal": solo "palabras que
// costaron", y siempre con la nota de que el puntaje usa un modelo de inglés estándar.
// Una palabra que costó: botón para escucharla, cómo se dice (IPA) y el sonido donde más costó.
const hardWord = (w) => `
  <li class="hard__word">
    <button type="button" class="hard__say" data-say="${esc(w.word)}" aria-label="${esc(t('app.report.live.pron.listen', { word: w.word }))}">${icon('volume', 20)}</button>
    <div class="hard__body">
      <p class="hard__head">
        <strong>${esc(w.word)}</strong>
        ${w.ipa ? `<span class="hard__ipa">/${esc(w.ipa)}/</span>` : ''}
        <span class="hard__score">${w.score}${w.times > 1 ? ` · ×${w.times}` : ''}</span>
      </p>
      ${
        w.sounds?.length
          ? `<p class="hard__sounds" aria-label="${esc(t('app.report.live.pron.sounds'))}">${w.sounds
              .map((s, i) => `<span class="hard__sound ${i === w.weakest_sound ? 'is-weak' : ''}">/${esc(s.ipa)}/ <b>${s.score}</b></span>`)
              .join('')}</p>`
          : ''
      }
      <div class="practice" data-practice-box="${esc(w.word)}" aria-live="polite"></div>
    </div>
  </li>`

const pronunciationCard = (p) => {
  const note = (text) => `<p class="pron__note">${esc(text)}</p>`
  if (p.status === 'pending') return `<div class="card is-pending"><p role="status">${t('app.report.live.pron.pending')}</p></div>`
  if (p.status === 'unavailable') {
    return `<section class="card"><h2 class="card__title">${t('app.report.live.pron.title')}</h2>${note(t(`app.report.live.pron.${p.reason}`))}</section>`
  }
  if (p.score == null) return ''
  const notes = [t('app.report.live.pron.fairness')]
  if (p.turns_partial) notes.push(t('app.report.live.pron.partial', { n: p.turns_partial }))
  if (p.turns_without_audio) notes.push(t('app.report.live.pron.someNoAudio', { n: p.turns_without_audio }))
  if (p.turns_over_quota) notes.push(t('app.report.live.pron.someQuota', { n: p.turns_over_quota }))
  if (p.turns_failed) notes.push(t('app.report.live.pron.someFailed', { n: p.turns_failed }))
  const words = p.hard_words.length
    ? `<p class="card__sub">${t('app.report.live.pron.hardText')}</p>
       <ul class="hard">${p.hard_words.map(hardWord).join('')}</ul>
       <p class="pron__note">${t('app.report.live.pron.ipaNote')}</p>`
    : `<p class="card__sub">${t('app.report.live.pron.noHard')}</p>`
  return `
    <section class="card">
      <h2 class="card__title">${t('app.report.live.pron.hardTitle')}</h2>
      ${words}
      ${notes.map(note).join('')}
    </section>`
}

function reportBody(r) {
  const notes = []
  if (r.user_turns === 0) notes.push(t('app.report.live.empty'))
  if (r.grammar.status === 'incomplete') notes.push(t('app.report.live.incomplete', { n: r.grammar.turns_failed }))
  return `
    ${notes.map((n) => `<div class="card is-pending"><p role="status">${esc(n)}</p></div>`).join('')}
    <section class="card">
      <h2 class="card__title">${t('app.report.scoresTitle')}</h2>
      <div class="scores">${ASPECT_ORDER.map((a) => scoreCard(a, r[ASPECT_FIELD[a]])).join('')}</div>
    </section>
    ${pronunciationCard(r.pronunciation)}
    ${fluencyCard(r.fluency)}
    ${errorsCard(r.grammar)}`
}

export const liveHead = () => ({ eyebrow: t('app.report.eyebrow'), title: t('app.report.title') })

export function renderLiveReport(p) {
  if (!/^\d+$/.test(p.id)) {
    return `<div class="card empty">
      <p>${t('app.report.notFound')}</p>
      <button class="btn btn--primary" type="button" data-nav="/app/conversaciones">${t('app.report.backList')}</button>
    </div>`
  }
  return `
    <section class="card report__head">
      <div class="report__info"><h2>${t('app.report.title')}</h2></div>
      <div class="report__actions">
        <button class="btn btn--navy" type="button" data-nav="/app/revision/${p.id}">${t('app.report.review')}</button>
        <button class="btn btn--outline" type="button" data-nav="/app/preparar">${icon('mic', 18)}${t('app.report.again')}</button>
      </div>
    </section>
    <div id="reportBody" aria-live="polite"></div>`
}

export function initLiveReport(root, p, scope) {
  const host = root.querySelector('#reportBody')
  if (!host) return
  let gone = false
  scope.onCleanup(() => (gone = true))

  const practice = createWordPractice(root, p.id, scope)

  const load = async ({ force = false } = {}) => {
    host.innerHTML = loading()
    try {
      const report = await getReport(p.id, { force })
      if (!gone) {
        host.innerHTML = reportBody(report)
        practice.mount(report.pronunciation.hard_words || [])
      }
    } catch (err) {
      if (!gone) host.innerHTML = failed(err)
    }
  }
  scope.listen(root, 'click', (e) => {
    if (e.target.closest('[data-retry]')) load({ force: true })
    const now = e.target.closest('[data-practice]')
    if (now) practice.toggle(now.dataset.practice)
    const say = e.target.closest('[data-say]')
    if (say) {
      if (!canSpeak) toast(t('app.practice.noSpeech'))
      else speak(say.dataset.say, { force: true, rate: 0.8 })
    }
  })
  load()
}
