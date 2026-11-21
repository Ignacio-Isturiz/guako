import './ring.css'
import { esc } from '@/features/app/utils/html.js'

// Anillo de puntaje (estilo "readiness" de Aura). Se anima al aparecer.
export function ring(value, { size = 96, stroke = 10, color = 'var(--blue)', label = value, sub = '', className = '' } = {}) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const off = c * (1 - Math.max(0, Math.min(100, value)) / 100)
  return `
    <div class="ring ${className}" style="--size:${size}px">
      <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" aria-hidden="true">
        <circle class="ring__track" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-width="${stroke}" fill="none"/>
        <circle class="ring__bar" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-width="${stroke}" fill="none"
          stroke="${color}" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${off}"
          style="--c:${c}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
      </svg>
      <div class="ring__label"><strong>${label}</strong>${sub ? `<small>${esc(sub)}</small>` : ''}</div>
    </div>`
}
