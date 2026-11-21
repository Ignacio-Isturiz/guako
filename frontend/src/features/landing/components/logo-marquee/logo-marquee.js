import './logo-marquee.css'
import logo from '@/shared/assets/brand/guako-logo.png'

// Tira pequeña con el logo + "GUAKO" que se desplaza sin fin (pie de la landing).
// El set se duplica para que el bucle sea continuo.
const SET = Array.from(
  { length: 8 },
  () => `<span class="logos__item"><img src="${logo}" alt="" width="22" height="22" draggable="false" /><span>GUAKO</span></span>`,
).join('')

export function renderLogoMarquee() {
  return `
    <div class="logos" aria-hidden="true">
      <div class="logos__track">${SET}${SET}</div>
    </div>`
}
