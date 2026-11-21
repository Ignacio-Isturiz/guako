// Cursor de pluma (solo dentro de `area`) y un desplume breve en cada clic de la página.
import './feathers.css'
import { listen, onCleanup } from '@/core/lifecycle.js'

const COLORS = ['#e8201a', '#ffc700', '#0a7cff', '#e8201a', '#0b2a6b']

// Pluma recortada en papel (borde crema, como las cartas)
const feather = (color) => `
  <svg viewBox="0 0 30 80" width="100%" height="100%" aria-hidden="true">
    <path d="M15 3 C28 17 30 44 15 74 C0 44 2 17 15 3 Z" fill="${color}" stroke="#fff6e0" stroke-width="2.4" stroke-linejoin="round"/>
    <g stroke="rgba(255,255,255,.38)" stroke-width="1.4" stroke-linecap="round" fill="none">
      <path d="M15 22 L8 15 M15 22 L22 15 M15 34 L6 26 M15 34 L24 26 M15 46 L6 38 M15 46 L24 38 M15 58 L9 52 M15 58 L21 52"/>
    </g>
    <path d="M15 12 L15 79" stroke="rgba(0,0,0,.3)" stroke-width="1.8" stroke-linecap="round"/>
  </svg>`

export function initFeathers(area) {
  if (!area) return
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const fine = matchMedia('(hover: hover) and (pointer: fine)').matches

  const layer = document.createElement('div')
  layer.className = 'feather-layer'
  document.body.appendChild(layer)
  onCleanup(() => {
    cancelAnimationFrame(raf)
    layer.remove()
  })

  /* ---------- Pluma que sigue al cursor ---------- */
  let cursor = null
  const pos = { x: -100, y: -100 } // posición suavizada
  const target = { x: -100, y: -100 }
  let rot = 25
  let hovering = false

  if (fine) {
    cursor = document.createElement('div')
    cursor.className = 'feather-cursor'
    cursor.innerHTML = `<div class="feather-cursor__in">${feather('#e8201a')}</div>`
    layer.appendChild(cursor)
  }

  /* ---------- Plumas que caen ---------- */
  const parts = []
  const burst = (x, y, count = 6, bias = 0) => {
    for (let i = 0; i < count; i++) {
      const el = document.createElement('div')
      el.className = 'feather'
      const w = 10 + Math.random() * 9
      el.style.width = `${w}px`
      el.style.height = `${w * 2.6}px`
      el.innerHTML = feather(COLORS[(Math.random() * COLORS.length) | 0])
      layer.appendChild(el)
      const ang = -Math.PI / 2 + (Math.random() - 0.5) * 2.8 + bias * 0.7
      const sp = 170 + Math.random() * 190
      parts.push({
        el,
        x,
        y,
        vx: Math.cos(ang) * sp,
        vy: Math.sin(ang) * sp,
        rot: Math.random() * 360,
        vr: (Math.random() - 0.5) * 700,
        ph: Math.random() * 6.28,
        life: 0,
        max: 0.6 + Math.random() * 0.35,
      })
    }
    if (cursor) {
      cursor.firstChild.classList.remove('is-pop')
      void cursor.offsetWidth
      cursor.firstChild.classList.add('is-pop')
    }
    run()
  }

  /* ---------- Bucle de animación (solo corre cuando hace falta) ---------- */
  let raf = 0
  let last = 0
  const run = () => {
    if (!raf) {
      last = performance.now()
      raf = requestAnimationFrame(frame)
    }
  }
  const frame = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000)
    last = now

    if (cursor) {
      const px = pos.x
      pos.x += (target.x - pos.x) * Math.min(1, dt * 16)
      pos.y += (target.y - pos.y) * Math.min(1, dt * 16)
      const vx = dt ? (pos.x - px) / dt : 0
      // La pluma se balancea según hacia dónde se mueve
      const want = 22 + Math.max(-45, Math.min(45, vx * 0.04))
      rot += (want - rot) * Math.min(1, dt * 9)
      const bob = Math.sin(now / 420) * 2
      cursor.style.transform = `translate3d(${pos.x - 15}px, ${pos.y - 80 + bob}px, 0) rotate(${rot}deg)`
    }

    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i]
      p.life += dt
      if (p.life >= p.max) {
        p.el.remove()
        parts.splice(i, 1)
        continue
      }
      // Frena rápido el impulso y cae despacio, aleteando de lado a lado
      const drag = Math.exp(-4.5 * dt)
      p.vx *= drag
      p.vy = p.vy * drag + 150 * dt * (1 - drag) * 8
      p.vy = Math.min(p.vy, 170)
      p.ph += dt * 9
      p.x += (p.vx + Math.sin(p.ph) * 40) * dt
      p.y += p.vy * dt
      p.rot += p.vr * dt
      p.vr *= Math.exp(-1.4 * dt)
      const t = p.life / p.max
      const alpha = t > 0.5 ? 1 - (t - 0.5) / 0.5 : 1
      p.el.style.opacity = alpha
      p.el.style.transform = `translate3d(${p.x}px, ${p.y}px, 0) rotate(${p.rot + Math.sin(p.ph) * 25}deg)`
    }

    if (parts.length || hovering) raf = requestAnimationFrame(frame)
    else raf = 0
  }

  /* ---------- Eventos ---------- */
  area.addEventListener('pointerenter', (e) => {
    hovering = true
    if (cursor) {
      pos.x = target.x = e.clientX
      pos.y = target.y = e.clientY
      cursor.classList.add('is-on')
    }
    run()
  })
  area.addEventListener('pointerleave', () => {
    hovering = false
    cursor?.classList.remove('is-on')
  })
  area.addEventListener('pointermove', (e) => {
    target.x = e.clientX
    target.y = e.clientY
  })

  // Cada clic (o toque) de la página suelta un desplume breve.
  // Si el usuario lanza la carta de un empujón dentro de la pila, salen unas pocas más.
  let down = null
  listen(document, 'pointerdown', (e) => {
    down = { x: e.clientX, y: e.clientY, inArea: area.contains(e.target) }
  })
  listen(document, 'pointerup', (e) => {
    if (!down) return
    const dx = e.clientX - down.x
    const dist = Math.hypot(dx, e.clientY - down.y)
    if (dist < 6) burst(e.clientX, e.clientY, 6)
    else if (dist > 80 && down.inArea) burst(e.clientX, e.clientY, 4, Math.sign(dx))
    down = null
  })
  listen(document, 'pointercancel', () => (down = null))
}
