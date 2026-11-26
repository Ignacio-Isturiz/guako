// Revisión real: la conversación guardada en el backend (GET /api/sessions/{id}/turns),
// con los errores del informe marcados en cada turno tuyo. Tu audio solo se conserva con
// consentimiento, así que aquí se puede reproducir únicamente la voz de Guako.
import { t } from '@/core/i18n.js'
import { getTurns, getReport, fetchReplyAudio, errorText } from '@/features/app/data/sessions-api.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { markText } from '@/features/app/utils/mark-text.js'
import { flagButton, openFlagReply } from '@/features/app/components/flag-reply/flag-reply.js'

export const liveReviewHead = () => ({ eyebrow: t('app.review.eyebrow'), title: t('app.review.title') })

const failed = (err) => `
  <div class="card empty">
    <p role="alert">${esc(errorText(err))}</p>
    <button class="btn btn--primary" type="button" data-retry>${t('app.report.live.retry')}</button>
  </div>`

// Errores de gramática del informe, agrupados por número de turno
function errorsByTurn(report) {
  const map = new Map()
  for (const e of report?.grammar?.errors ?? []) map.set(e.turn_number, [...(map.get(e.turn_number) ?? []), e])
  return map
}

function userBubble(turn, errors, checked) {
  const n = errors.length
  const badge = checked
    ? `<span class="rv__badge ${n ? 'has-errors' : 'is-clean'}">${n ? t('app.review.errorsFound', { n }) : t('app.review.allGood')}</span>`
    : ''
  const notes = n
    ? `<ol class="rv__notes">${errors
        .map((e) => `<li><s>${esc(e.original)}</s> → <b>${esc(e.correction)}</b><span>${esc(e.explanation)}</span></li>`)
        .join('')}</ol>`
    : ''
  return `
    <li class="rv rv--user">
      <span class="rv__who">${t('app.talk.you')}</span>
      <div class="rv__bubble"><p>${markText(turn.user_transcript, errors.map((e) => e.original))}</p>${badge}${notes}</div>
    </li>`
}

const guakoBubble = (turn) => `
  <li class="rv rv--guako">
    <span class="rv__who">Guako</span>
    <div class="rv__bubble">
      <p>${esc(turn.reply_text)}</p>
      <div class="rv__audio">
        <button type="button" class="say say--sm" data-play="${esc(turn.reply_audio_url)}" aria-label="${t('app.review.playGuako')}">${icon('volume', 16)}</button>
        ${flagButton(turn.turn_number)}
      </div>
    </div>
  </li>`

function reviewBody(turns, report, sessionId) {
  const byTurn = errorsByTurn(report)
  // Solo se marcan los turnos que el análisis revisó; sin informe, la conversación se ve sin marcas
  const checked = !!report && report.grammar.status !== 'empty'
  const totalErrors = [...byTurn.values()].reduce((sum, list) => sum + list.length, 0)
  let note = ''
  if (!report) note = `<p class="card__sub" role="status">${t('app.review.live.noMarks')}</p>`
  else if (report.grammar.status === 'incomplete')
    note = `<p class="card__sub" role="status">${esc(t('app.report.live.incomplete', { n: report.grammar.turns_failed }))}</p>`

  // Un turno guardado son dos burbujas: lo que dijiste y lo que respondió Guako
  // La apertura de Guako (turno 0) no tiene lo que dijiste: solo se pinta su burbuja
  const list = turns
    .map((tn) => (tn.user_transcript ? userBubble(tn, byTurn.get(tn.turn_number) ?? [], checked) : '') + guakoBubble(tn))
    .join('')
  const spoken = turns.filter((tn) => tn.user_transcript).length
  return `
    <div class="review">
      <section class="card review__main">
        <p class="card__sub">${t('app.review.intro')}</p>
        ${note}
        <ol class="rvlist">${list}</ol>
      </section>
      <aside class="review__aside">
        <div class="card">
          <h2 class="card__eyebrow">${t('app.review.summary')}</h2>
          <ul class="review__stats">
            <li><strong>${spoken}</strong><span>${t('app.review.userTurns')}</span></li>
            ${report ? `<li><strong>${totalErrors}</strong><span>${t('app.review.errorsTotal')}</span></li>` : ''}
          </ul>
          <button class="btn btn--navy btn--block" type="button" data-nav="/app/informe/${sessionId}">${t('app.review.toReport')}</button>
        </div>
      </aside>
    </div>`
}

export function renderLiveReview(p) {
  if (!/^\d+$/.test(p.id)) {
    return `<div class="card empty"><p>${t('app.review.notFound')}</p>
      <button class="btn btn--primary" type="button" data-nav="/app/conversaciones">${t('app.report.backList')}</button></div>`
  }
  return `<div id="reviewBody" aria-live="polite"><div class="card"><p>${icon('spinner', 22)} ${t('app.review.live.loading')}</p></div></div>`
}

export function initLiveReview(root, p, scope) {
  const host = root.querySelector('#reviewBody')
  if (!host) return
  let gone = false
  let audio = null
  const stop = () => {
    audio?.pause()
    audio = null
  }
  scope.onCleanup(() => {
    gone = true
    stop()
  })

  const load = async () => {
    try {
      // El informe es opcional aquí: si falla, la conversación se muestra sin errores marcados
      const [turns, report] = await Promise.all([getTurns(p.id), getReport(p.id).catch(() => null)])
      if (gone) return
      host.innerHTML = turns.length
        ? reviewBody(turns, report, p.id)
        : `<div class="card empty"><p>${t('app.review.live.empty')}</p></div>`
    } catch (err) {
      if (!gone) host.innerHTML = failed(err)
    }
  }

  scope.listen(root, 'click', async (e) => {
    if (e.target.closest('[data-retry]')) return load()
    const flag = e.target.closest('[data-flag]')
    if (flag) return openFlagReply({ sessionId: Number(p.id), turnNumber: Number(flag.dataset.flag) })
    const play = e.target.closest('[data-play]')
    if (!play) return
    stop()
    try {
      const url = URL.createObjectURL(await fetchReplyAudio(play.dataset.play))
      if (gone) return URL.revokeObjectURL(url)
      audio = new Audio(url)
      audio.onended = () => URL.revokeObjectURL(url)
      await audio.play()
    } catch (err) {
      play.title = errorText(err)
    }
  })
  load()
}
