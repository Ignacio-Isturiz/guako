import './side-columns.css'

// Columnas decorativas a los lados del hero (solo se ven en pantallas anchas).
// Cada columna es una tira de ilustraciones que se desplaza sin fin.
const SIDE_HEIGHTS = [230, 280, 245, 300, 235, 270, 290, 255]
const SIDE_TILTS = [-3, 2.5, -1.5, 3, -2.5, 1.5, -2, 2]

function column(c, list) {
  const shift = (c * 3) % list.length
  const items = [...list.slice(shift), ...list.slice(0, shift)]
  const html = items
    .map(
      (b, i) => `
      <div class="side-card" style="--h:${SIDE_HEIGHTS[(i + c * 2) % 8]}px; --tilt:${SIDE_TILTS[(i + c) % 8]}deg">
        <img src="${b.img}" alt="" width="320" height="320" loading="lazy" draggable="false" />
      </div>`,
    )
    .join('')
  // Contenido duplicado para que el bucle sea continuo
  return `
    <div class="sidecol sidecol--${c % 2 ? 'b' : 'a'} ${c % 2 ? 'sidecol--down' : ''}" style="--dur:${78 + c * 11}s">
      <div class="sidecol__track">${html}${html}</div>
    </div>`
}

// list: [{ img }] · devuelve las dos zonas (izquierda y derecha) con dos columnas cada una
export function renderSideColumns(list) {
  return `
    <div class="hero__side hero__side--left" aria-hidden="true">${column(0, list)}${column(1, list)}</div>
    <div class="hero__side hero__side--right" aria-hidden="true">${column(2, list)}${column(3, list)}</div>`
}
