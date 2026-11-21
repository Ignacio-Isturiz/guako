import './phrase-carousel.css'

// Carrusel infinito de frases (inglés + traducción) con su etiqueta de rol o tema.
// phrases: [{ kind: 'rol' | 'tema', tag, en, es }] · attrs: atributos extra para el contenedor
const phrase = (p, i) => `
  <div class="phrase" style="--tilt:${i % 2 ? 1.5 : -1.5}deg">
    <span class="phrase__tag phrase__tag--${p.kind}">${p.tag}</span>
    <strong>${p.en}</strong>
    <span class="phrase__es">${p.es}</span>
  </div>`

export function renderPhraseCarousel({ label, phrases, attrs = '' }) {
  const cards = phrases.map(phrase).join('')
  // El contenido va duplicado para que el bucle sea continuo
  return `
    <div class="phrases" ${attrs}>
      <p class="phrases__label">${label}</p>
      <div class="phrases__window" aria-hidden="true">
        <div class="phrases__track">${cards}${cards}</div>
      </div>
    </div>`
}
