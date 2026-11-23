import './informe.css'
import { t } from '@/core/i18n.js'
import { ASPECTS, getConversation, aspectStatus } from '@/features/app/data/store.js'
import { speak } from '@/features/app/services/tts.js'
import { ring } from '@/features/app/components/ring/ring.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { roleArt as art } from '@/shared/assets/illustrations/index.js'
import { explain } from '@/features/app/utils/explain.js'
import { topicName, fmtDate } from '@/features/app/utils/format.js'
import { aspectName, ASPECT_COLOR, tone, toneText } from '@/features/app/utils/scores.js'
import { toast } from '@/features/app/components/toast/toast.js'
import { DEMO_MODE } from '@/features/app/data/config.js'
import { liveHead, renderLiveReport, initLiveReport } from './informe-live.js'

const RING_COLOR = { high: '#1aa05a', mid: '#f0a500', low: '#e8201a' }
const STATUS_ICON = { waiting: 'clock', processing: 'spinner', ready: 'check' }

const notFound = () => `
  <div class="card empty">
    <p>${t('app.report.notFound')}</p>
    <button class="btn btn--primary" type="button" data-nav="/app/conversaciones">${t('app.report.backList')}</button>
  </div>`

// Estado de cada aspecto: en espera, en proceso o listo
const statusStrip = (st) => `
  <ul class="status" aria-label="${t('app.report.eyebrow')}">
    ${ASPECTS.map(
      (a, i) => `<li class="status__item is-${st[i]}">
        <span class="status__ic">${icon(STATUS_ICON[st[i]], 16)}</span>
        <span><strong>${aspectName(a)}</strong><small>${t(`app.status.${st[i]}`)}</small></span>
      </li>`,
    ).join('')}
  </ul>`

const scoreCard = (c, a, i, st) => {
  const v = c.scores[a]
  const ready = st[i] === 'ready'
  return `
    <div class="score ${ready ? '' : 'is-pending'}">
      ${
        ready
          ? ring(v, { size: 84, stroke: 9, color: ASPECT_COLOR[a] })
          : `<div class="ring ring--ghost" style="--size:84px"><span>${icon(STATUS_ICON[st[i]], 22)}</span></div>`
      }
      <strong>${aspectName(a)}</strong>
      <small>${ready ? toneText(v) : t(`app.status.${st[i]}`)}</small>
    </div>`
}

function body(c, st) {
  const all = st.every((s) => s === 'ready')
  const any = st.some((s) => s === 'ready')
  return `
    <div class="report__top">
      <div class="card overall">
        ${
          all
            ? ring(c.overall, { size: 132, stroke: 13, color: RING_COLOR[tone(c.overall)], sub: t('app.report.overall') })
            : `<div class="ring ring--ghost" style="--size:132px"><span>${icon('spinner', 34)}</span></div>`
        }
        <p>${all ? `<b>${toneText(c.overall)}</b>` : t('app.report.analyzing')}</p>
      </div>
      <div class="card">
        <h2 class="card__eyebrow">${all ? t('app.report.allReady') : t('app.report.analyzing')}</h2>
        ${statusStrip(st)}
      </div>
    </div>

    <section class="card positive ${any ? '' : 'is-pending'}">
      <h2 class="card__title">${icon('star', 20)}${t('app.report.positiveTitle')}</h2>
      <p>${any ? explain(c.positive) : t('app.report.pending')}</p>
    </section>

    <section class="card">
      <h2 class="card__title">${t('app.report.scoresTitle')}</h2>
      <div class="scores">${ASPECTS.map((a, i) => scoreCard(c, a, i, st)).join('')}</div>
    </section>

    ${
      all
        ? `
    <section class="card">
      <h2 class="card__title">${t('app.report.errorsTitle')}</h2>
      <p class="card__sub">${t('app.report.errorsText', { n: c.errors.length })}</p>
      <ol class="errors">
        ${c.errors.map((e, i) => `<li><span class="errors__n">${i + 1}</span><div><strong>${explain(e.title)}</strong><p>${explain(e.detail)}</p></div></li>`).join('')}
      </ol>
    </section>

    <section class="card">
      <h2 class="card__title">${t('app.report.phrasesTitle')}</h2>
      <div class="phrases-fix">
        ${c.phrases
          .map(
            (p) => `<article class="fix">
              <div class="fix__said"><small>${t('app.report.said')}</small><p>${esc(p.said)}</p></div>
              <div class="fix__better"><small>${t('app.report.better')}</small><p>${esc(p.better)}</p></div>
              <div class="fix__why"><small>${t('app.report.why')}</small><p>${explain(p.why)}</p></div>
            </article>`,
          )
          .join('')}
      </div>
    </section>

    <section class="card">
      <h2 class="card__title">${t('app.report.wordsTitle')}</h2>
      <ul class="words">
        ${c.words
          .map(
            (w) => `<li class="word">
              <button type="button" class="say" data-say="${esc(w.word)}" aria-label="${t('app.report.listen')}: ${esc(w.word)}">${icon('volume', 20)}</button>
              <div><strong>${esc(w.word)}</strong><span class="ipa">${esc(w.ipa)}</span><small>${explain(w.tip)}</small></div>
            </li>`,
          )
          .join('')}
      </ul>
      <button class="btn btn--navy" type="button" data-nav="/app/practica">${icon('ear', 18)}${t('app.report.toPractice')}</button>
    </section>`
        : `<div class="card is-pending"><p>${t('app.report.pending')}</p></div>`
    }`
}

// Con backend, el informe es el de la sesión real; los ids de ejemplo ("c_seed_1") siguen siendo locales
const isLive = (p) => !DEMO_MODE && !getConversation(p.id)

// 5. Informe: estado del análisis, puntajes, errores, frases corregidas y palabras con audio
export default {
  head: (p) => {
    if (isLive(p)) return liveHead()
    const c = getConversation(p.id)
    return { eyebrow: t('app.report.eyebrow'), title: c ? topicName(c) : t('app.report.title') }
  },
  render(p) {
    if (isLive(p)) return renderLiveReport(p)
    const c = getConversation(p.id)
    if (!c) return notFound()
    return `
      <section class="card report__head">
        <div class="thumb thumb--lg"><img src="${art(c.art)}" alt="" width="160" height="160" /></div>
        <div class="report__info">
          <h2>${t('app.report.title')}</h2>
          <p>${esc(t('app.report.meta', { date: fmtDate(c.date), min: c.durationMin, level: c.level }))}</p>
        </div>
        <div class="report__actions">
          <button class="btn btn--navy" type="button" data-nav="/app/revision/${c.id}">${t('app.report.review')}</button>
          <button class="btn btn--outline" type="button" data-nav="/app/preparar">${icon('mic', 18)}${t('app.report.again')}</button>
        </div>
      </section>
      <div id="reportBody"></div>`
  },
  init(root, p, scope) {
    if (isLive(p)) return initLiveReport(root, p, scope)
    const c = getConversation(p.id)
    if (!c) return
    const host = root.querySelector('#reportBody')
    let lastKey = ''
    const paint = () => {
      const st = aspectStatus(c)
      const key = st.join()
      if (key === lastKey) return
      lastKey = key
      host.innerHTML = body(c, st)
      return st.every((s) => s === 'ready')
    }
    // El análisis termina aspecto por aspecto: se revisa cada medio segundo
    if (!paint()) {
      const id = scope.every(() => paint() && clearInterval(id), 500)
    }
    scope.listen(root, 'click', (e) => {
      const b = e.target.closest('[data-say]')
      if (b) speak(b.dataset.say, { force: true, rate: 0.85 }).catch?.(() => toast(t('app.practice.noSpeech')))
    })
  },
}
