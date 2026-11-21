import './progreso.css'
import { t } from '@/core/i18n.js'
import { ASPECTS, conversations } from '@/features/app/data/store.js'
import { esc } from '@/features/app/utils/html.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { fmtDate } from '@/features/app/utils/format.js'
import { aspectName, ASPECT_COLOR } from '@/features/app/utils/scores.js'

const DAY = 864e5
const W = 760
const H = 300
const M = { l: 38, r: 16, t: 14, b: 34 }

const inRange = (list, range) => (range === 'all' ? list : list.filter((c) => Date.now() - new Date(c.date) <= Number(range) * DAY))

function chart(list, hidden) {
  const n = list.length
  const lo = 40
  const hi = 100
  const x = (i) => M.l + (n === 1 ? 0 : (i / (n - 1)) * (W - M.l - M.r))
  const y = (v) => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b)
  const grid = [40, 60, 80, 100]
    .map((g) => `<line x1="${M.l}" x2="${W - M.r}" y1="${y(g)}" y2="${y(g)}" class="grid"/><text x="${M.l - 8}" y="${y(g) + 4}" text-anchor="end" class="axis">${g}</text>`)
    .join('')
  const step = Math.max(1, Math.ceil(n / 7))
  const xs = list
    .map((c, i) => (i % step === 0 || i === n - 1 ? `<text x="${x(i)}" y="${H - 10}" text-anchor="middle" class="axis">${fmtDate(c.date)}</text>` : ''))
    .join('')
  const lines = ASPECTS.filter((a) => !hidden.has(a))
    .map((a) => {
      const pts = list.map((c, i) => `${x(i).toFixed(1)},${y(c.scores[a]).toFixed(1)}`)
      return `<polyline points="${pts.join(' ')}" fill="none" stroke="${ASPECT_COLOR[a]}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
        ${list.map((c, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(c.scores[a]).toFixed(1)}" r="4.5" fill="#fff" stroke="${ASPECT_COLOR[a]}" stroke-width="3"/>`).join('')}`
    })
    .join('')
  return { svg: `${grid}${xs}${lines}<line class="guide" id="guide" x1="0" x2="0" y1="${M.t}" y2="${H - M.b}" hidden/>`, x }
}

// 7. Progreso: evolución de los cinco puntajes a lo largo del tiempo
export default {
  head: () => ({ eyebrow: t('app.progress.eyebrow'), title: t('app.progress.title') }),
  render() {
    return `
      <div class="progress">
        <div class="progress__bar">
          <div class="seg" role="group" aria-label="${t('app.progress.title')}">
            ${['7', '30', 'all'].map((r) => `<button type="button" data-range="${r}">${t(`app.progress.range.${r}`)}</button>`).join('')}
          </div>
        </div>
        <div id="progBody"></div>
      </div>`
  },
  init(root, _p, scope) {
    const all = conversations().reverse() // de la más antigua a la más reciente
    let range = 'all'
    const hidden = new Set()
    const body = root.querySelector('#progBody')

    const paint = () => {
      root.querySelectorAll('[data-range]').forEach((b) => b.classList.toggle('is-on', b.dataset.range === range))
      const list = inRange(all, range)
      if (list.length < 2) {
        body.innerHTML = `<div class="card empty"><p>${t('app.progress.empty')}</p>
          <button class="btn btn--primary" type="button" data-nav="/app/preparar">${icon('mic', 18)}${t('app.progress.emptyBtn')}</button></div>`
        return
      }
      const first = list[0]
      const last = list[list.length - 1]
      const avg = (c) => Math.round(ASPECTS.reduce((s, a) => s + c.scores[a], 0) / ASPECTS.length)
      const delta = avg(last) - avg(first)
      const sorted = [...ASPECTS].sort((a, b) => last.scores[b] - last.scores[a])
      const { svg, x } = chart(list, hidden)

      body.innerHTML = `
        <div class="tiles">
          <div class="card tile"><small>${t('app.progress.avg')}</small><strong>${avg(last)}</strong>
            <span class="delta ${delta >= 0 ? 'is-up' : 'is-down'}">${delta >= 0 ? '▲' : '▼'} ${Math.abs(delta)} ${t('app.progress.change').toLowerCase()}</span></div>
          <div class="card tile"><small>${t('app.progress.best')}</small><strong style="color:${ASPECT_COLOR[sorted[0]]}">${aspectName(sorted[0])}</strong><span>${t('app.progress.points', { n: last.scores[sorted[0]] })}</span></div>
          <div class="card tile"><small>${t('app.progress.weak')}</small><strong style="color:${ASPECT_COLOR[sorted[4]]}">${aspectName(sorted[4])}</strong><span>${t('app.progress.points', { n: last.scores[sorted[4]] })}</span></div>
        </div>

        <section class="card chartcard">
          <h2 class="card__title">${t('app.progress.chartTitle')}</h2>
          <div class="legend" role="group" aria-label="${esc(t('app.progress.legend'))}">
            ${ASPECTS.map((a) => `<button type="button" class="legend__item ${hidden.has(a) ? 'is-off' : ''}" data-aspect="${a}" aria-pressed="${!hidden.has(a)}">
              <i style="background:${ASPECT_COLOR[a]}"></i>${aspectName(a)}</button>`).join('')}
          </div>
          <p class="card__sub">${t('app.progress.legend')}</p>
          <div class="chart" id="chart">
            <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${t('app.progress.chartTitle')}">${svg}</svg>
            <div class="tip" id="tip" hidden></div>
          </div>
        </section>`

      // Al pasar el cursor se ven los cinco puntajes de esa conversación
      const chartEl = body.querySelector('#chart')
      const guide = body.querySelector('#guide')
      const tip = body.querySelector('#tip')
      const svgEl = chartEl.querySelector('svg')
      const move = (e) => {
        const rect = svgEl.getBoundingClientRect()
        const px = ((e.clientX - rect.left) / rect.width) * W
        let best = 0
        list.forEach((_, i) => {
          if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i
        })
        const c = list[best]
        guide.hidden = false
        guide.setAttribute('x1', x(best))
        guide.setAttribute('x2', x(best))
        tip.hidden = false
        tip.style.left = `${(x(best) / W) * 100}%`
        tip.innerHTML = `<b>${fmtDate(c.date)}</b>${ASPECTS.filter((a) => !hidden.has(a))
          .map((a) => `<span><i style="background:${ASPECT_COLOR[a]}"></i>${aspectName(a)} <strong>${c.scores[a]}</strong></span>`)
          .join('')}`
      }
      chartEl.addEventListener('pointermove', move)
      chartEl.addEventListener('pointerleave', () => {
        guide.hidden = true
        tip.hidden = true
      })
    }

    scope.listen(root, 'click', (e) => {
      const r = e.target.closest('[data-range]')
      if (r) {
        range = r.dataset.range
        return paint()
      }
      const a = e.target.closest('[data-aspect]')
      if (a) {
        const id = a.dataset.aspect
        hidden.has(id) ? hidden.delete(id) : hidden.size < ASPECTS.length - 1 && hidden.add(id)
        paint()
      }
    })
    paint()
  },
}
