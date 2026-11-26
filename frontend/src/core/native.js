// Ajustes que solo aplican dentro de la app móvil (Capacitor). En la web no hace nada.
//
// - Botón "atrás" de Android: primero cierra el modal abierto (como Esc), luego retrocede en el
//   historial y, si ya no hay a dónde volver, sale de la app.
// - Barra de estado: texto oscuro sobre las pantallas claras de la app y claro sobre las azules
//   (landing, acceso, conversación, páginas legales).
// - haptic(): vibración corta (al empezar y soltar el botón de hablar).
import { Capacitor } from '@capacitor/core'

export const isNative = Capacitor.isNativePlatform()

export async function initNative() {
  if (!isNative) return
  const { App } = await import('@capacitor/app')
  App.addListener('backButton', ({ canGoBack }) => {
    if (document.querySelector('[aria-modal="true"]')) {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    } else if (canGoBack) {
      history.back()
    } else {
      App.exitApp()
    }
  })

  const { StatusBar, Style } = await import('@capacitor/status-bar')
  let last = ''
  const syncStatusBar = () => {
    // La pantalla ya está pintada cuando corre (después de routechange/authchange)
    setTimeout(() => {
      const light = !!document.querySelector('.app') && !document.querySelector('.talk')
      const style = light ? Style.Light : Style.Dark // Light = texto oscuro (fondo claro)
      if (style === last) return
      last = style
      StatusBar.setStyle({ style }).catch(() => {})
    }, 0)
  }
  syncStatusBar()
  window.addEventListener('routechange', syncStatusBar)
  window.addEventListener('authchange', syncStatusBar)
}

export async function haptic(strength = 'Light') {
  if (!isNative) return
  try {
    const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
    await Haptics.impact({ style: ImpactStyle[strength] ?? ImpactStyle.Light })
  } catch {
    /* sin vibración: no pasa nada */
  }
}
