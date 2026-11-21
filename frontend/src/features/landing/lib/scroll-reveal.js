import { listen } from '@/core/lifecycle.js'

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v))
const easeOut = (k) => 1 - Math.pow(1 - k, 3)

// Entrada ligada al scroll: cada [data-reveal] de la sección recibe --pi (0 a 1)
// según cuánto se ha visto la sección; el CSS lo usa con calc((1 - var(--pi, 1)) * …).
// `data-d` (0 a 1) es el momento en que esa pieza empieza a entrar.
// `onUpdate` se llama después de cada cálculo (p. ej. para dibujar flechas).
export function initScrollReveal(section, { onUpdate } = {}) {
  if (!section || matchMedia('(prefers-reduced-motion: reduce)').matches) return

  const items = [...section.querySelectorAll('[data-reveal]')].map((el) => ({
    el,
    d: parseFloat(el.dataset.d || '0'),
  }))

  const update = () => {
    const top = section.getBoundingClientRect().top
    // 0 cuando la sección asoma por abajo; 1 cuando casi llega arriba
    const p = clamp((innerHeight - top) / (innerHeight * 0.85))
    items.forEach(({ el, d }) => el.style.setProperty('--pi', easeOut(clamp((p - d) / (1 - d))).toFixed(3)))
    onUpdate?.()
  }

  listen(window, 'scroll', update, { passive: true })
  listen(window, 'resize', update)
  update()
}
