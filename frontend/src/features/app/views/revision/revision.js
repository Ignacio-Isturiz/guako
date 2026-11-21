import './revision.css'
import { t } from '@/core/i18n.js'
import { getConversation } from '@/features/app/data/store.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { roleArt as art } from '@/shared/assets/illustrations/index.js'
import { explain, gloss } from '@/features/app/utils/explain.js'
import { topicName, fmtDate } from '@/features/app/utils/format.js'
import { toast } from '@/features/app/components/toast/toast.js'

// Marca en el texto del usuario cada fragmento con error (numerado)
function markText(text, notes) {
  const ranges = []
  notes.forEach((n, i) => {
    const at = text.indexOf(n.frag)
    if (at >= 0) ranges.push({ at, len: n.frag.length, i })
  })
  ranges.sort((a, b) => a.at - b.at)
  let out = ''
  let cur = 0
  for (const r of ranges) {
    if (r.at < cur) continue
    out += `${esc(text.slice(cur, r.at))}<mark class="err">${esc(text.slice(r.at, r.at + r.len))}<sup>${r.i + 1}</sup></mark>`
    cur = r.at + r.len
  }
  return out + esc(text.slice(cur))
}

const mmss = (s) => `0:${String(s).padStart(2, '0')}`

function turn(tn, idx) {
  if (tn.who === 'guako') {
    return `
      <li class="rv rv--guako">
        <span class="rv__who">Guako</span>
        <div class="rv__bubble"><p>${esc(tn.text)}</p>${gloss(tn.gloss) ? `<small>${gloss(tn.gloss)}</small>` : ''}</div>
      </li>`
  }
  const n = tn.notes.length
  return `
    <li class="rv rv--user" id="turn-${idx}">
      <span class="rv__who">${t('app.talk.you')}</span>
      <div class="rv__bubble">
        <p>${markText(tn.text, tn.notes)}</p>
        <div class="rv__audio">
          <button type="button" class="say say--sm" data-audio aria-label="${t('app.review.play')}">${icon('play', 16)}</button>
          <span class="wave-bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>
          <small>${t('app.review.audio')} · ${mmss(tn.sec)}</small>
        </div>
        <span class="rv__badge ${n ? 'has-errors' : 'is-clean'}">${n ? t('app.review.errorsFound', { n }) : t('app.review.allGood')}</span>
        ${
          n
            ? `<ol class="rv__notes">${tn.notes
                .map((x) => `<li><s>${esc(x.frag)}</s> → <b>${esc(x.better)}</b><span>${explain(x.why)}</span></li>`)
                .join('')}</ol>`
            : ''
        }
      </div>
    </li>`
}

// 6. Revisar lo dicho: texto completo con errores marcados y el audio de cada turno
export default {
  head: (p) => {
    const c = getConversation(p.id)
    return { eyebrow: t('app.review.eyebrow'), title: c ? topicName(c) : t('app.review.title') }
  },
  render(p) {
    const c = getConversation(p.id)
    if (!c) {
      return `<div class="card empty"><p>${t('app.review.notFound')}</p>
        <button class="btn btn--primary" type="button" data-nav="/app/conversaciones">${t('app.report.backList')}</button></div>`
    }
    const userTurns = c.turns.filter((x) => x.who === 'user')
    const errs = userTurns.reduce((s, x) => s + x.notes.length, 0)
    return `
      <div class="review">
        <section class="card review__main">
          <p class="card__sub">${t('app.review.intro')}</p>
          <ol class="rvlist">${c.turns.map(turn).join('')}</ol>
        </section>
        <aside class="review__aside">
          <div class="card">
            <h2 class="card__eyebrow">${t('app.review.summary')}</h2>
            <p class="review__date">${fmtDate(c.date, { weekday: 'long', day: 'numeric', month: 'long' })}</p>
            <ul class="review__stats">
              <li><strong>${userTurns.length}</strong><span>${t('app.review.userTurns')}</span></li>
              <li><strong>${errs}</strong><span>${t('app.review.errorsTotal')}</span></li>
            </ul>
            <button class="btn btn--navy btn--block" type="button" data-nav="/app/informe/${c.id}">${t('app.review.toReport')}</button>
          </div>
        </aside>
      </div>`
  },
  init(root, _p, scope) {
    // El audio real llega con el backend; por ahora se avisa en vez de simular un sonido
    scope.listen(root, 'click', (e) => {
      if (e.target.closest('[data-audio]')) toast(t('app.review.audioDemo'))
    })
  },
}
