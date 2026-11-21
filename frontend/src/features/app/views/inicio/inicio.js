import './inicio.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t } from '@/core/i18n.js'
import { getSession } from '@/features/auth/index.js'
import { conversations, lastConversation, streak, practiceItems } from '@/features/app/data/store.js'
import { ring } from '@/features/app/components/ring/ring.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { roleArt as art } from '@/shared/assets/illustrations/index.js'
import { topicName, fmtDate, fmtWeekday, greeting, firstName } from '@/features/app/utils/format.js'
import { tone, ASPECT_COLOR } from '@/features/app/utils/scores.js'

const RING_COLOR = { high: '#1aa05a', mid: '#f0a500', low: '#e8201a' }

// Mini gráfica de los últimos puntajes generales
function sparkline(list) {
  const pts = [...list].reverse().slice(-8).map((c) => c.overall)
  if (pts.length < 2) return ''
  const W = 220
  const H = 64
  const min = Math.min(...pts) - 4
  const max = Math.max(...pts) + 4
  const xy = pts.map((v, i) => [(i / (pts.length - 1)) * W, H - ((v - min) / (max - min)) * H])
  const d = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
  const [lx, ly] = xy[xy.length - 1]
  return `<svg class="spark" viewBox="-6 -6 ${W + 12} ${H + 12}" aria-hidden="true">
    <path d="${d} L${W} ${H} L0 ${H} Z" fill="url(#sg)" opacity=".5"/>
    <defs><linearGradient id="sg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#0a7cff" stop-opacity=".35"/><stop offset="1" stop-color="#0a7cff" stop-opacity="0"/></linearGradient></defs>
    <path d="${d}" fill="none" stroke="#0a7cff" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${lx}" cy="${ly}" r="5.5" fill="#0a7cff" stroke="#fff" stroke-width="3"/></svg>`
}

function streakCard() {
  const s = streak()
  const label = s.count === 0 ? t('app.home.streakNone') : s.count === 1 ? t('app.home.streakOne') : t('app.home.streakMany', { n: s.count })
  const note = s.today ? t('app.home.streakToday') : s.count ? t('app.home.streakKeep') : t('app.home.streakStart')
  return `
    <article class="card streak">
      <h2 class="card__eyebrow">${t('app.home.streakTitle')}</h2>
      <div class="streak__big ${s.count ? 'is-on' : ''}">${icon('flame', 44)}<strong>${s.count}</strong></div>
      <p class="streak__text"><b>${label}</b><br />${note}</p>
      <div class="week" aria-hidden="true">
        ${s.week
          .map(
            (d) => `<span class="week__day ${d.done ? 'is-done' : ''} ${d.isToday ? 'is-today' : ''}">
              <i>${d.done ? icon('check', 14) : ''}</i><small>${fmtWeekday(d.date)}</small></span>`,
          )
          .join('')}
      </div>
    </article>`
}

function lastCard(c) {
  if (!c) {
    return `
      <article class="card last last--empty">
        <h2 class="card__eyebrow">${t('app.home.lastTitle')}</h2>
        <img src="${logo}" alt="" width="72" height="72" />
        <p>${t('app.home.lastEmpty')}</p>
        <button class="btn btn--primary" type="button" data-nav="/app/preparar">${t('app.home.heroBtn')}</button>
      </article>`
  }
  return `
    <article class="card last">
      <h2 class="card__eyebrow">${t('app.home.lastTitle')}</h2>
      <div class="last__row">
        <div class="thumb"><img src="${art(c.art)}" alt="" width="120" height="120" /></div>
        <div class="last__info">
          <h3>${esc(topicName(c))}</h3>
          <p>${fmtDate(c.date)} · ${t('app.list.min', { n: c.durationMin })} · <span class="chip chip--sm">${c.level}</span></p>
        </div>
        ${ring(c.overall, { size: 92, stroke: 10, color: RING_COLOR[tone(c.overall)], sub: t('app.home.overall') })}
      </div>
      <div class="last__actions">
        <button class="btn btn--navy" type="button" data-nav="/app/informe/${c.id}">${t('app.home.report')}</button>
        <button class="btn btn--outline" type="button" data-nav="/app/revision/${c.id}">${t('app.home.review')}</button>
      </div>
    </article>`
}

// 2. Inicio: botón principal, racha y acceso rápido a la última conversación
export default {
  head: () => ({ eyebrow: greeting(), title: firstName(getSession()?.name) }),
  render() {
    const name = firstName(getSession()?.name)
    const list = conversations()
    const last = list[0] || null
    const words = practiceItems().length
    return `
      <section class="hero-card" aria-labelledby="homeHero">
        <div class="hero-card__copy">
          <h2 id="homeHero">${t('app.home.heroTitle')}</h2>
          <p>${t('app.home.heroText')}</p>
          <button class="btn btn--primary btn--lg" type="button" data-nav="/app/preparar">${icon('mic', 22)}${t('app.home.heroBtn')}</button>
        </div>
        <div class="hero-card__art" aria-hidden="true">
          <span class="hero-card__bubble">${esc(t('app.home.bubble', { name }))}</span>
          <img class="hero-card__mascot" src="${logo}" alt="" width="200" height="200" />
          <img class="hero-card__sticker s1" src="${art('viajes')}" alt="" width="90" height="90" />
          <img class="hero-card__sticker s2" src="${art('mesero')}" alt="" width="90" height="90" />
        </div>
      </section>

      <div class="grid grid--home">
        ${streakCard()}
        ${lastCard(last)}
        <article class="card mini">
          <h2 class="card__eyebrow">${t('app.home.progressTitle')}</h2>
          ${sparkline(list) || `<div class="spark spark--empty"></div>`}
          <p>${t('app.home.progressText')}</p>
          <button class="btn btn--outline btn--sm" type="button" data-nav="/app/progreso">${t('app.home.progressBtn')}</button>
        </article>
        <article class="card mini">
          <h2 class="card__eyebrow">${t('app.home.practiceTitle')}</h2>
          <div class="mini__big">${icon('ear', 34)}<strong>${words}</strong></div>
          <p>${t('app.home.practiceText', { n: words })}</p>
          <button class="btn btn--outline btn--sm" type="button" data-nav="/app/practica">${t('app.home.practiceBtn')}</button>
        </article>
      </div>`
  },
}
