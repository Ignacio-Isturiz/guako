import './shell.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { t, getLang } from '@/core/i18n.js'
import { getSession } from '@/features/auth/index.js'
import { icon } from '@/features/app/components/icon/icon.js'
import { esc } from '@/features/app/utils/html.js'
import { isDemo, bannerHidden } from '@/features/app/data/store.js'
import { streak, loadStreak } from '@/features/app/data/streak.js'

// Menú principal (los apartados de MVP.md: Inicio, Mis conversaciones, Progreso, Práctica, Ajustes)
const NAV = [
  { name: 'inicio', path: '/app/inicio', icon: 'home', key: 'home', match: ['inicio'] },
  { name: 'conversaciones', path: '/app/conversaciones', icon: 'chat', key: 'conversations', tab: 'history', match: ['conversaciones', 'informe', 'revision'] },
  { name: 'progreso', path: '/app/progreso', icon: 'chart', key: 'progress', match: ['progreso'] },
  { name: 'practica', path: '/app/practica', icon: 'ear', key: 'practice', match: ['practica'] },
  { name: 'ajustes', path: '/app/ajustes', icon: 'gear', key: 'settings', match: ['ajustes'] },
]

const initial = (name = '') => esc((name.trim()[0] || '?').toUpperCase())

const navItem = (n) => `
  <a class="side__link" href="${n.path}" data-nav="${n.path}" data-item="${n.name}" data-match="${n.match.join(' ')}">
    ${icon(n.icon, 22)}<span>${t(`app.nav.${n.key}`)}</span>
  </a>`

const tabItem = (n) => `
  <a class="tab" href="${n.path}" data-nav="${n.path}" data-match="${n.match.join(' ')}" aria-label="${t(`app.nav.${n.key}`)}">
    ${icon(n.icon, 22)}<span>${t(`app.nav.${n.tab || n.key}`)}</span>
  </a>`

export function renderShell() {
  const user = getSession() || {}
  const lang = getLang()
  const pill = (code) =>
    `<button type="button" data-lang="${code}" aria-pressed="${lang === code}" ${lang === code ? 'class="is-on"' : ''}>${code.toUpperCase()}</button>`
  const tabs = NAV.map(tabItem)
  return `
    <div class="app">
      <aside class="side" aria-label="${t('app.nav.menu')}">
        <a class="side__brand" href="/app/inicio" data-nav="/app/inicio" aria-label="Guako">
          <img src="${logo}" alt="" width="40" height="40" /><span>GUAKO</span>
        </a>
        <button class="btn btn--primary side__cta" type="button" data-nav="/app/preparar">${icon('mic', 20)}<span>${t('app.nav.start')}</span></button>
        <nav class="side__nav">${NAV.map(navItem).join('')}</nav>
        <div class="side__foot">
          <div class="side__user">
            <span class="user-av" aria-hidden="true">${initial(user.name)}</span>
            <span class="side__who"><strong>${esc(user.name || '')}</strong><small>${esc(user.email || '')}</small></span>
          </div>
          <button class="side__logout" type="button" data-action="app-logout">${icon('logout', 18)}<span>${t('app.nav.logout')}</span></button>
        </div>
      </aside>

      <div class="app__main">
        <header class="top">
          <div class="top__title">
            <p class="top__eyebrow" id="topEyebrow"></p>
            <h1 id="topTitle"></h1>
          </div>
          <div class="top__right">
            <span class="chip chip--streak" id="topStreak" title="${t('app.home.streakTitle')}"></span>
            <div class="lang" role="group" aria-label="${t('app.nav.language')}">${pill('es')}${pill('en')}</div>
          </div>
        </header>
        <div id="demoBanner"></div>
        <main class="view" id="view" tabindex="-1"></main>
      </div>

      <nav class="tabbar" aria-label="${t('app.nav.menu')}">
        ${tabs.slice(0, 2).join('')}
        <button class="tabbar__fab" type="button" data-nav="/app/preparar" aria-label="${t('app.nav.start')}">${icon('mic', 26)}</button>
        ${tabs.slice(2).join('')}
      </nav>
    </div>`
}

// Contador de racha de la barra superior
function paintStreak() {
  const chip = document.querySelector('#topStreak')
  if (!chip) return
  const s = streak()
  chip.classList.toggle('is-on', s.status === 'done')
  chip.classList.toggle('is-warn', s.status === 'recoverable')
  chip.innerHTML = `${icon('flame', 18)}<strong>${s.count}</strong>`
}
window.addEventListener('streakchange', paintStreak)

// Marca el apartado activo y actualiza título, racha y aviso de modo demo
export function updateChrome(routeName, head) {
  document.querySelectorAll('[data-match]').forEach((el) => {
    const on = el.dataset.match.split(' ').includes(routeName)
    el.classList.toggle('is-on', on)
    on ? el.setAttribute('aria-current', 'page') : el.removeAttribute('aria-current')
  })
  const eyebrow = document.querySelector('#topEyebrow')
  const title = document.querySelector('#topTitle')
  if (eyebrow) eyebrow.textContent = head.eyebrow || ''
  if (title) title.textContent = head.title || ''
  document.title = `${head.title} · Guako`

  paintStreak()
  loadStreak() // trae el estado real del servidor; al llegar dispara 'streakchange'

  const banner = document.querySelector('#demoBanner')
  if (banner) {
    banner.innerHTML =
      isDemo() && !bannerHidden()
        ? `<div class="demo-note" role="note">
             <span>${t('app.demoBanner.text')}</span>
             <span class="demo-note__actions">
               <button type="button" class="link" data-action="demo-fresh">${t('app.demoBanner.fresh')}</button>
               <button type="button" class="link" data-action="demo-hide">${t('app.demoBanner.hide')}</button>
             </span>
           </div>`
        : ''
  }
}
