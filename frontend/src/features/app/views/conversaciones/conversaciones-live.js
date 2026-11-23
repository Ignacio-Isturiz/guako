// Mis conversaciones reales: el historial guardado en el backend (GET /api/sessions).
// Usa los estilos de conversaciones.css; aún no hay puntaje por conversación, solo informe y revisión.
import { t } from '@/core/i18n.js'
import { listSessions, errorText } from '@/features/app/data/sessions-api.js'
import { artOf, minutesOf } from '@/features/app/data/history.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { roleArt as art } from '@/shared/assets/illustrations/index.js'
import { fmtDate } from '@/features/app/utils/format.js'

// Los puntajes que ya existen (gramática y fluidez); si el informe aún no se abrió, no hay ninguno
function scores(s) {
  const items = [['gram', s.grammar_score], ['fluency', s.fluency_score]].filter(([, v]) => v != null)
  if (!items.length) return `<span class="conv__analyzing">${t('app.list.live.noScore')}</span>`
  return items.map(([a, v]) => `<span class="chip chip--sm">${t(`app.aspects.${a}`)} <b>${v}</b></span>`).join(' ')
}

function row(s) {
  const ended = !!s.ended_at
  return `
    <li class="conv">
      <div class="thumb"><img src="${art(artOf(s.topic))}" alt="" width="96" height="96" /></div>
      <div class="conv__info">
        <h3>${esc(s.topic)}</h3>
        <p>${fmtDate(s.created_at, { weekday: 'short', day: 'numeric', month: 'short' })} · ${t('app.list.min', { n: minutesOf(s.duration_seconds) })}
          · <span class="chip chip--sm">${esc(s.level)}</span>
          ${s.role ? `· ${esc(s.role)}` : ''}
          ${ended ? '' : `· <span class="chip chip--sm">${t('app.list.live.open')}</span>`}</p>
      </div>
      <div class="conv__score">${scores(s)}</div>
      <div class="conv__actions">
        ${ended ? `<button class="btn btn--navy btn--sm" type="button" data-nav="/app/informe/${s.id}">${t('app.list.report')}</button>` : ''}
        <button class="btn btn--outline btn--sm" type="button" data-nav="/app/revision/${s.id}">${t('app.list.review')}</button>
      </div>
    </li>`
}

export function renderLiveList() {
  return `
    <div class="listbar">
      <label class="search">${icon('search', 20)}<input type="search" id="q" placeholder="${esc(t('app.list.search'))}" aria-label="${esc(t('app.list.search'))}" /></label>
    </div>
    <p class="listcount" id="count"></p>
    <ul class="convlist" id="list" aria-live="polite"><li class="card empty"><p>${icon('spinner', 22)} ${t('app.list.live.loading')}</p></li></ul>`
}

export function initLiveList(root, scope) {
  const list = root.querySelector('#list')
  const count = root.querySelector('#count')
  let all = []
  let q = ''
  let gone = false
  scope.onCleanup(() => (gone = true))

  const paint = () => {
    const term = q.trim().toLowerCase()
    const items = all.filter((s) => !term || `${s.topic} ${s.role ?? ''}`.toLowerCase().includes(term))
    count.textContent = all.length ? t('app.list.count', { n: items.length }) : ''
    if (!all.length) {
      list.innerHTML = `<li class="card empty"><p>${t('app.list.empty')}</p>
        <button class="btn btn--primary" type="button" data-nav="/app/preparar">${icon('mic', 18)}${t('app.list.emptyBtn')}</button></li>`
    } else if (!items.length) {
      list.innerHTML = `<li class="card empty"><p>${t('app.list.noResults')}</p></li>`
    } else {
      list.innerHTML = items.map(row).join('')
    }
  }

  const load = async () => {
    try {
      all = await listSessions()
      if (!gone) paint()
    } catch (err) {
      if (gone) return
      count.textContent = ''
      list.innerHTML = `<li class="card empty"><p role="alert">${esc(errorText(err))}</p>
        <button class="btn btn--primary" type="button" data-retry>${t('app.report.live.retry')}</button></li>`
    }
  }

  scope.listen(root, 'click', (e) => {
    if (e.target.closest('[data-retry]')) load()
  })
  scope.listen(root.querySelector('#q'), 'input', (e) => {
    q = e.target.value
    paint()
  })
  load()
}
