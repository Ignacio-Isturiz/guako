import './cta.css'
import '@/features/landing/components/mark/mark.css'
import logo from '@/shared/assets/brand/guako-logo.png'
import { roleArt } from '@/shared/assets/illustrations/index.js'
import { t } from '@/core/i18n.js'
import { initScrollReveal } from '@/features/landing/lib/scroll-reveal.js'
import { renderVoiceDemo, initVoiceDemo } from '@/features/landing/components/voice-demo/voice-demo.js'
import { renderLogoMarquee } from '@/features/landing/components/logo-marquee/logo-marquee.js'

// Sección 4 (azul): "Empieza a hablar" + demo de voz + enlaces legales + tira de logos.

// Pegatinas de los lados: ilustración, lado y posición
const STICKERS = [
  { img: 'entrevistador', side: 'left', top: '15%', x: '4%', tilt: -5, d: 0.1 },
  { img: 'mesero', side: 'left', top: '58%', x: '9%', tilt: 4, d: 0.25 },
  { img: 'viajes', side: 'right', top: '12%', x: '7%', tilt: 5, d: 0.18 },
  { img: 'vida-diaria', side: 'right', top: '56%', x: '4%', tilt: -4, d: 0.32 },
]

const sticker = (s, i) => `
  <figure class="sticker sticker--${s.side}" data-reveal="${s.side === 'left' ? 'left' : 'right'}" data-d="${s.d}"
    style="top:${s.top}; ${s.side}:${s.x}; --tilt:${s.tilt}deg; --fd:${5 + i * 0.6}s; --fdelay:${-i * 1.3}s">
    <img src="${roleArt(s.img) || logo}" alt="" width="300" height="300" draggable="false" />
  </figure>`

export function renderCta() {
  return `
    <section class="cta" id="empieza">
      <div class="cta__stickers" aria-hidden="true">${STICKERS.map(sticker).join('')}</div>

      <div class="cta__inner">
        <h2 data-reveal="up" data-d="0"><span class="mark">${t('cta.title')}</span>${t('cta.titleRest')}</h2>
        <p class="cta__lead" data-reveal="up" data-d="0.06">${t('cta.lead')}</p>

        ${renderVoiceDemo({ attrs: 'data-reveal="pop" data-d="0.14"' })}

        <div class="cta__buttons" data-reveal="up" data-d="0.3">
          <button class="btn btn--primary" type="button" data-auth="register">${t('cta.start')}</button>
          <button class="btn btn--ghost" type="button" data-auth="login">${t('cta.login')}</button>
        </div>
      </div>

      <nav class="cta__legal" aria-label="${t('legal.tabs')}">
        <button type="button" data-legal="terms">${t('footer.terms')}</button>
        <span aria-hidden="true">·</span>
        <button type="button" data-legal="privacy">${t('footer.privacy')}</button>
      </nav>

      ${renderLogoMarquee()}
    </section>
  `
}

export function initCta() {
  const section = document.querySelector('.cta')
  if (!section) return
  initScrollReveal(section)
  initVoiceDemo(section)
}
