import './conversaciones.css'
import { t } from '@/core/i18n.js'
import { TOPICS } from '@/features/app/data/seed.js'
import { conversations, aspectStatus } from '@/features/app/data/store.js'
import { ring } from '@/features/app/components/ring/ring.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { roleArt as art } from '@/shared/assets/illustrations/index.js'
import { topicName, fmtDate } from '@/features/app/utils/format.js'
import { tone } from '@/features/app/utils/scores.js'

const RING_COLOR = { high: '#1aa05a', mid: '#f0a500', low: '#e8201a' }

function row(c) {
  const analyzing = !aspectStatus(c).every((s) => s === 'ready')
  return `
    <li class="conv">
      <div class="thumb"><img src="${art(c.art)}" alt="" width="96" height="96" /></div>
      <div class="conv__info">
        <h3>${esc(topicName(c))}</h3>
        <p>${fmtDate(c.date, { weekday: 'short', day: 'numeric', month: 'short' })} · ${t('app.list.min', { n: c.durationMin })}
          · <span class="chip chip--sm">${c.level}</span></p>
      </div>
      <div class="conv__score">
        ${
          analyzing
            ? `<span class="conv__analyzing">${icon('spinner', 18)}${t('app.list.analyzing')}</span>`
            : ring(c.overall, { size: 62, stroke: 7, color: RING_COLOR[tone(c.overall)] })
        }
      </div>
      <div class="conv__actions">
        <button class="btn btn--navy btn--sm" type="button" data-nav="/app/informe/${c.id}">${t('app.list.report')}</button>
        <button class="btn btn--outline btn--sm" type="button" data-nav="/app/revision/${c.id}">${t('app.list.review')}</button>
      </div>
    </li>`
}

// 8. Mis conversaciones: fecha, tema y puntaje general, con acceso al informe y a la revisión
export default {
  head: () => ({ eyebrow: t('app.list.eyebrow'), title: t('app.list.title') }),
  render() {
    return `
      <div class="listbar">
        <label class="search">${icon('search', 20)}<input type="search" id="q" placeholder="${esc(t('app.list.search'))}" aria-label="${esc(t('app.list.search'))}" /></label>
        <div class="chips" role="group">
          <button type="button" class="chipbtn is-on" data-topic="all">${t('app.list.all')}</button>
          ${TOPICS.map((tp) => `<button type="button" class="chipbtn" data-topic="${tp.id}">${t(`app.topics.${tp.id}.name`)}</button>`).join('')}
        </div>
      </div>
      <p class="listcount" id="count"></p>
      <ul class="convlist" id="list"></ul>`
  },
  init(root, _p, scope) {
    const all = conversations()
    let topic = 'all'
    let q = ''
    const list = root.querySelector('#list')
    const count = root.querySelector('#count')

    const paint = () => {
      root.querySelectorAll('[data-topic]').forEach((b) => b.classList.toggle('is-on', b.dataset.topic === topic))
      const term = q.trim().toLowerCase()
      const items = all.filter((c) => (topic === 'all' || c.topicId === topic) && (!term || topicName(c).toLowerCase().includes(term)))
      count.textContent = t('app.list.count', { n: items.length })
      if (!all.length) {
        list.innerHTML = `<li class="card empty"><p>${t('app.list.empty')}</p>
          <button class="btn btn--primary" type="button" data-nav="/app/preparar">${icon('mic', 18)}${t('app.list.emptyBtn')}</button></li>`
        count.textContent = ''
      } else if (!items.length) {
        list.innerHTML = `<li class="card empty"><p>${t('app.list.noResults')}</p></li>`
      } else {
        list.innerHTML = items.map(row).join('')
      }
    }

    scope.listen(root, 'click', (e) => {
      const b = e.target.closest('[data-topic]')
      if (b) {
        topic = b.dataset.topic
        paint()
      }
    })
    scope.listen(root.querySelector('#q'), 'input', (e) => {
      q = e.target.value
      paint()
    })
    paint()
  },
}
