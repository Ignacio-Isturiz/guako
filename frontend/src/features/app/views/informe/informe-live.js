// Informe real: se pide al backend (GET /api/sessions/{id}/report) en lugar de usar datos de ejemplo.
// Solo se pintan puntajes que el backend calculó: lo que aún no existe sale como "pendiente".
import { t } from '@/core/i18n.js'
import { getReport, errorText } from '@/features/app/data/sessions-api.js'
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
  const sub = score != null ? toneText(score) : t(pending ? 'app.report.live.pending' : 'app.report.live.noData')
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

  const load = async ({ force = false } = {}) => {
    host.innerHTML = loading()
    try {
      const report = await getReport(p.id, { force })
      if (!gone) host.innerHTML = reportBody(report)
    } catch (err) {
      if (!gone) host.innerHTML = failed(err)
    }
  }
  scope.listen(root, 'click', (e) => {
    if (e.target.closest('[data-retry]')) load({ force: true })
  })
  load()
}
