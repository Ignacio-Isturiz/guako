// Web instalable: registra el service worker (public/sw.js) para que Chrome en Android ofrezca
// "Instalar aplicación" directo desde el botón de la landing. En la app nativa no se usa.
export function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* sin service worker la web funciona igual; solo no se ofrece instalar directo */
    })
  })
}
